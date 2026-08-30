# SPDX-License-Identifier: GPL-3.0-or-later
"""
Parser for the JUMPX ".x" format (300 Heroes, older engine).

Despite the extension this is NOT a DirectX .x file. Signature is
"JUMPX V5.01", the vendor is jumpw.com.

Standalone:
    python eg3d_x.py path/to/020_skin2.x

=============================================================================
 FORMAT
=============================================================================
    0x00   "JUMPX V5.01" + advertising strings, NUL padded
    0x50   u32 = 8            (version?)
    0x54   u32 = 300          (size of the table of contents)
    0x58   TOC: [4 byte tag][u32 size = 4][u32 value] repeated
           n<x> = count of section <x>, a<x> = START offset inside block 1
           tags: tex mtl geo bon bgp att rib prt act ... plus some singletons
    ....   u32 x4 = (rawSize1, rawSize2, packedSize1, packedSize2)
           zlib stream 1  -> block 1, the descriptors
           zlib stream 2  -> block 2, the payload

Every 4 byte "pointer" inside block 1 is an address with base 1_000_000_000;
subtract it to get an offset into block 2. They are NOT 4 byte aligned, so a
scan on word boundaries misses them.

BLOCK 2 is partitioned exactly, with no slack:
    materials   nmtl * 11484        (11484 = frames*16 + 44)
    geo structs ngeo * 2860         (2860  = frames*4)
    mesh data   see below
    bones       nbon * 20020        (20020 = frames*12 + frames*16)
"frames" is the length of the single global animation timeline (715 in the
reference file); every clip is a range on it.

MESH BUFFERS, back to back, per mesh:
    positions  vc * 12   float32 x3
    normals    vc * 12   float32 x3   -- already unit length, nothing to crack
    uv         vc *  8   float32 x2
    palette    vc *  1   uint8 index into the bgp bone palette table,
                         saturating at 255
    indices    tc *  6   uint16 x3, plain triangle list
    skin       vc * 24   byte0 ?, bytes 1..4 bone indices (uint8),
                         bytes 8..23 four float32 weights, sum exactly 1.0

BONE DESCRIPTORS in block 1, at abon, stride 172:
    +8    u32 offset of the bone name inside block 1
    +144  u32 address of this bone's animation data in block 2
The name table doubles as the hierarchy: each entry is
    [name NUL][u32 child index] * n
A child index is recognisable because bytes 2..4 of the word are zero, which
no ASCII name can be.

BONE ANIMATION per bone, in block 2:
    +0     frames * 12   float32 x3   world position per frame
    +8580  frames * 16   float32 x4   world quaternion x,y,z,w per frame

FRAME 0 IS THE BIND POSE. Verified on the reference file: transforming each
bone's dominant vertices into that bone's local space clusters them at 8% of
the model diagonal, the best of all 715 frames, and the bone positions sit
2.64 units from their weighted vertex centroid on a model 98 units across.
So inverseBind = inverse(frame 0), and there is no separate bind matrix.

GEO DESCRIPTORS in block 1, at ageo, stride 124:
    +8 name offset, +16 material index, +28 vertex count,
    +32 triangle count, +36 block 2 address

ACTIONS in block 1, at aact, stride 90:
    +0  name, 80 bytes NUL padded
    +80 u16 first frame, +82 u16 last frame  (inclusive, on the global timeline)
=============================================================================
"""

import os
import struct
import zlib

try:
    import numpy as np
except Exception:  # pragma: no cover
    np = None

ADDR_BASE = 1000000000
BONE_STRIDE = 172
GEO_STRIDE = 124
ACT_STRIDE = 90
MTL_STRIDE = 48
# A bone's animation block is frames * one of these. The base is
# 12 (position) + 16 (quaternion) = 28; on top of that a file may carry a
# 12 byte scale track and/or one extra 4 byte float per frame:
#   28 = pos + rot                 (020_skin2.x)
#   32 = pos + rot + extra         (156_skin10.x)
#   40 = pos + rot + scale         (045.x, most bones)
#   44 = pos + rot + scale + extra (045.x, four bones)
# Listing them explicitly keeps the frame-count solver unambiguous.
BYTES_PER_FRAME = (28, 32, 40, 44)
SCALE_MIN_BPF = 40
TEX_STRIDE = 8
BONE_NAME_FIELD = 8


class XParseError(Exception):
    pass


class XBone(object):
    def __init__(self):
        self.index = 0
        self.name = ""
        self.parent = -1
        self.children = []
        self.pos = None    # (frames, 3) float32
        self.quat = None   # (frames, 4) float32, x y z w
        self.scale = None  # (frames, 3) float32 or None
        self.visible = None  # (frames,) bool or None -- per frame on/off


class XMesh(object):
    def __init__(self):
        self.name = ""
        self.material = 0
        self.verts = None
        self.normals = None
        self.uvs = None
        self.tris = None
        self.bone_idx = None
        self.weights = None
        self.palette = None  # uint8 index into the bone palette table (bgp)


class XClip(object):
    def __init__(self):
        self.name = ""
        self.start = 0
        self.end = 0
        self.synthetic = False   # not declared in the file, covers everything


class XModel(object):
    def __init__(self):
        self.path = ""
        self.tags = {}
        self.textures = []
        self.materials = []   # list of dict(texture=index or None)
        self.meshes = []
        self.bones = []
        self.clips = []
        self.frames = 0


def is_jumpx(path):
    try:
        with open(path, "rb") as fh:
            return fh.read(5) == b"JUMPX"
    except OSError:
        return False


def _cstr(buf, off, limit=256):
    if not (0 <= off < len(buf)):
        return None
    end = buf.find(b"\x00", off, off + limit)
    if end < 0:
        return None
    raw = buf[off:end]
    if not raw:
        return None
    for enc in ("ascii", "gbk", "gb18030"):
        try:
            return raw.decode(enc)
        except (UnicodeDecodeError, LookupError):
            continue
    # Chinese names are GBK and can end on a truncated multi byte sequence,
    # so drop the incomplete tail rather than falling back to mojibake.
    for enc in ("gbk", "gb18030"):
        try:
            out = raw.decode(enc, errors="ignore")
            if out:
                return out
        except LookupError:
            continue
    return raw.decode("latin-1")


def parse_jumpx(path, log=None):
    if np is None:
        raise XParseError("numpy is required")
    if os.path.isdir(path):
        raise XParseError("%r is a folder, not a .x file" % path)
    with open(path, "rb") as fh:
        data = fh.read()
    if data[:5] != b"JUMPX":
        raise XParseError("not a JUMPX file (magic is %r)" % data[:5])

    model = XModel()
    model.path = path
    sig = _cstr(data, 0) or "JUMPX"
    if log:
        log.info("signature: %s   file size %d", sig, len(data))

    # ---- table of contents ------------------------------------------------
    off = 0x58
    while off + 12 <= len(data):
        tag = data[off:off + 4]
        if not all(32 <= c < 127 for c in tag):
            break
        size = struct.unpack_from("<I", data, off + 4)[0]
        if size != 4:
            break
        model.tags[tag.decode()] = struct.unpack_from("<I", data, off + 8)[0]
        off += 12
    t = model.tags
    if log:
        log.info("TOC: %d entries, ends at %d", len(t), off)
        log.info("  textures=%d materials=%d meshes=%d bones=%d actions=%d",
                 t.get("ntex", 0), t.get("nmtl", 0), t.get("ngeo", 0),
                 t.get("nbon", 0), t.get("nact", 0))
        log.debug("  raw TOC: %s", t)

    raw1, raw2, pk1, pk2 = struct.unpack_from("<4I", data, off)
    off += 16
    if log:
        log.info("payload: block1 %d -> %d bytes, block2 %d -> %d bytes",
                 pk1, raw1, pk2, raw2)

    d1 = zlib.decompressobj()
    B1 = d1.decompress(data[off:])
    consumed = len(data) - len(d1.unused_data)
    d2 = zlib.decompressobj()
    B2 = d2.decompress(data[consumed:])
    if log:
        log.info("decompressed: block1 %d bytes, block2 %d bytes", len(B1), len(B2))
    if len(B1) != raw1 or len(B2) != raw2:
        if log:
            log.warn("decompressed sizes differ from the header (%d/%d vs %d/%d)",
                     len(B1), len(B2), raw1, raw2)

    nbon = t.get("nbon", 0)
    ngeo = t.get("ngeo", 0)
    nact = t.get("nact", 0)
    abon = t.get("abon", 0)
    aact = t.get("aact", 0)

    # ---- clips first: they bound the timeline --------------------------
    for k in range(nact):
        base = aact + k * ACT_STRIDE
        if base + ACT_STRIDE > len(B1):
            break
        c = XClip()
        c.name = (_cstr(B1, base) or "clip_%d" % k)
        c.start, c.end = struct.unpack_from("<HH", B1, base + 80)
        model.clips.append(c)

    # ---- bone blocks ----------------------------------------------------
    # Each bone descriptor carries the address of its animation block. The
    # blocks are NOT all the same size: 020_skin2.x stores 28 bytes per frame
    # (position + rotation), 045.x stores 40 for most bones (plus a scale
    # track) and 44 for four of them (plus one more float). So the block size
    # must be read per bone instead of assumed.
    addrs = []
    for k in range(nbon):
        base = abon + k * BONE_STRIDE
        if base + 148 > len(B1):
            break
        a = struct.unpack_from("<I", B1, base + 144)[0] - ADDR_BASE
        if not (0 <= a < len(B2)):
            raise XParseError("bone %d has an implausible block address %d" % (k, a))
        addrs.append(a)
    if len(addrs) != nbon:
        raise XParseError("only %d of %d bone descriptors are readable"
                          % (len(addrs), nbon))
    order = sorted(range(nbon), key=lambda i: addrs[i])
    sizes = [0] * nbon
    for j, i in enumerate(order):
        nxt = addrs[order[j + 1]] if j + 1 < len(order) else len(B2)
        sizes[i] = nxt - addrs[i]
    if min(sizes) <= 0:
        raise XParseError("bone blocks overlap")

    model.frames = _solve_frames(sizes, addrs, B2, model.clips, log)
    frames = model.frames
    if log:
        per = sorted({s // frames for s in sizes})
        log.info("timeline: %d frames; %d bone blocks, %s bytes per frame "
                 "(28 = pos+rot, 32 = +extra, 40 = +scale, 44 = +both)",
                 frames, nbon, "/".join(str(p) for p in per))

    for k in range(nbon):
        b = XBone()
        b.index = k
        base = abon + k * BONE_STRIDE
        noff = struct.unpack_from("<I", B1, base + BONE_NAME_FIELD)[0]
        nm = _cstr(B1, noff)
        b.name = nm if nm and nm[:1].isalpha() else "Bone_%02d" % k
        o = addrs[k]
        b.pos = np.frombuffer(B2, dtype="<f4", count=frames * 3,
                              offset=o).reshape(frames, 3)
        b.quat = np.frombuffer(B2, dtype="<f4", count=frames * 4,
                               offset=o + frames * 12).reshape(frames, 4)
        bpf = sizes[k] // frames
        if bpf >= SCALE_MIN_BPF:
            b.scale = np.frombuffer(B2, dtype="<f4", count=frames * 3,
                                    offset=o + frames * 28).reshape(frames, 3)
        if bpf in (32, 44):
            # The trailing 4 bytes per frame are a uint32 that only ever holds
            # 0 or 1: a per frame VISIBILITY flag for the bone and whatever
            # hangs off it. Established from the clip correlation -- in 045.x
            # 'Bone17' is on exactly during single_skill_04_a and _04_b, and in
            # 156_skin10.x 'Bone01_dance_zhibao1' is on exactly during the clip
            # named dance_zhibao1. The bones carrying it are effect and prop
            # attachment points (_tx, _fx, _zhibao, Dummy01).
            flag = np.frombuffer(B2, dtype="<u4", count=frames,
                                 offset=o + frames * (28 if bpf == 32 else 40))
            b.visible = flag.astype(bool)
        model.bones.append(b)

    _sanitise_tracks(model, log)

    # Some files carry animation without declaring a single clip -- the
    # 045_skin5_huicheng.x effect set has 211 frames in which 110 of 120 bones
    # move, but nact = 0. Iterating over the clip list would silently throw all
    # of that away, so cover the whole timeline with one synthetic clip.
    if not model.clips and frames > 1:
        moved = 0
        for b in model.bones:
            if (np.abs(b.pos - b.pos[0]).max() > 1e-5
                    or np.abs(b.quat - b.quat[0]).max() > 1e-5):
                moved += 1
        if moved:
            c = XClip()
            c.name = "full_timeline"
            c.start = 0
            c.end = frames - 1
            c.synthetic = True
            model.clips.append(c)
            if log:
                log.info("the file declares no clips, but %d of %d bones move "
                         "over %d frames -- added one synthetic clip "
                         "'full_timeline' covering everything",
                         moved, nbon, frames)
        elif log:
            log.info("the file declares no clips and no bone moves: static asset")

    if log:
        ns = sum(1 for b in model.bones if b.scale is not None)
        if ns:
            log.info("bones: %d of %d carry a per-frame scale track", ns, nbon)
        nv = [b for b in model.bones if b.visible is not None]
        if nv:
            switching = [b for b in nv if b.visible.any() and not b.visible.all()]
            log.info("bones: %d of %d carry a per-frame visibility flag, %d of "
                     "them actually switch: %s", len(nv), nbon, len(switching),
                     ", ".join(b.name for b in switching[:6]))

    _parse_hierarchy(model, B1, log)

    if log and model.bones:
        q = np.concatenate([b.quat for b in model.bones])
        ln = np.linalg.norm(q, axis=1)
        log.info("bones: %d, quaternion length min %.5f max %.5f",
                 len(model.bones), ln.min(), ln.max())
        named = sum(1 for b in model.bones if not b.name.startswith("Bone_"))
        log.info("bone names resolved: %d/%d; roots: %s", named, len(model.bones),
                 [b.name for b in model.bones if b.parent < 0][:6])

    # ---- textures ---------------------------------------------------------
    # The section is a TABLE of [u32 flags][u32 nameOffset], and the names sit
    # after it. Reading the name right behind each entry only works by
    # accident when there is exactly one texture.
    atex = t.get("atex", 0)
    for i in range(t.get("ntex", 0)):
        b = atex + i * TEX_STRIDE
        if b + 8 > len(B1):
            break
        _flags, noff = struct.unpack_from("<II", B1, b)
        nm = _cstr(B1, noff)
        if nm:
            model.textures.append(nm)
        elif log:
            log.warn("texture %d: name offset %d is not readable", i, noff)
    if log:
        log.info("textures: %s", model.textures)

    # ---- materials --------------------------------------------------------
    # 48 bytes each; field at +12 is the index into the texture list.
    amtl = t.get("amtl", 0)
    for i in range(t.get("nmtl", 0)):
        b = amtl + i * MTL_STRIDE
        if b + MTL_STRIDE > len(B1):
            break
        tex = struct.unpack_from("<I", B1, b + 12)[0]
        model.materials.append({"texture": tex if tex < len(model.textures) else None})
        if log:
            log.info("material %d -> texture %s", i,
                     model.textures[tex] if tex < len(model.textures) else "none")


    # ---- meshes -----------------------------------------------------------
    ageo = t.get("ageo", 0)
    _atex_dummy = None
    for g in range(ngeo):
        base = ageo + g * GEO_STRIDE
        # +12 is the mesh index, +16 is the MATERIAL index. They coincide on
        # some files, which is how reading +12 went unnoticed.
        noff = struct.unpack_from("<I", B1, base + 8)[0]
        matidx = struct.unpack_from("<I", B1, base + 16)[0]
        vc, tc = struct.unpack_from("<II", B1, base + 28)

        # Every buffer has its OWN address in the descriptor. Computing the
        # offsets by stacking sizes only works while no optional buffer is
        # present -- 156_skin10.x carries an extra 4 bytes per vertex on some
        # meshes and not on others, which silently shifted the index buffer.
        def addr(field):
            v = struct.unpack_from("<I", B1, base + field)[0]
            o = v - ADDR_BASE
            return o if 0 <= o < len(B2) else None

        a_pos, a_nrm, a_uv = addr(36), addr(44), addr(52)
        a_byte, a_idx, a_skin = addr(68), addr(76), addr(92)
        if a_pos is None:
            if vc == 0 or tc == 0:
                if log:
                    log.info("mesh %d is empty (%d verts, %d tris), skipped",
                             g, vc, tc)
            elif log:
                log.warn("mesh %d has no usable position buffer address "
                         "(%d verts), skipped", g, vc)
            continue
        # fall back to the packed layout if a field is missing
        if a_nrm is None:
            a_nrm = a_pos + vc * 12
        if a_uv is None:
            a_uv = a_nrm + vc * 12
        if a_byte is None:
            a_byte = a_uv + vc * 8
        if a_idx is None:
            a_idx = a_byte + vc
        if a_skin is None:
            a_skin = a_idx + tc * 6

        m = XMesh()
        m.name = _cstr(B1, noff) or "mesh_%d" % g
        m.material = matidx
        m.verts = np.frombuffer(B2, dtype="<f4", count=vc * 3,
                                offset=a_pos).reshape(vc, 3)
        m.normals = np.frombuffer(B2, dtype="<f4", count=vc * 3,
                                  offset=a_nrm).reshape(vc, 3)
        m.uvs = np.frombuffer(B2, dtype="<f4", count=vc * 2,
                              offset=a_uv).reshape(vc, 2)
        # One byte per vertex: the index of this vertex's bone palette in the
        # bgp table. Verified on all 20514 vertices of 045_skin5_huicheng.x --
        # bgp[byte] equals the bone list stored inline in the skin record,
        # 100.0000%, and the used indices cover 0..186 for nbgp = 187.
        # It saturates at 255, so files with more than 255 palettes cannot
        # express the higher indices; those vertices all read 255. Since the
        # bone indices sit in the skin record anyway, the byte is redundant
        # for importing and is kept only for inspection.
        m.palette = np.frombuffer(B2, dtype="<u1", count=vc, offset=a_byte)
        tris = np.frombuffer(B2, dtype="<u2", count=tc * 3,
                             offset=a_idx).reshape(tc, 3).astype(np.int32)
        # Some meshes are padded with 0xFFFF placeholder indices. Those
        # triangles cannot be built; drop them instead of letting them poison
        # everything downstream.
        keep = (tris < vc).all(axis=1)
        dropped = int((~keep).sum())
        if dropped:
            tris = tris[keep]
            if log:
                log.warn("mesh %d '%s': %d of %d triangles reference vertices "
                         "that do not exist (0xFFFF padding), dropped",
                         g, m.name, dropped, tc)
        m.tris = tris
        skin = np.frombuffer(B2, dtype="<u1", count=vc * 24,
                             offset=a_skin).reshape(vc, 24)
        m.bone_idx = skin[:, 1:5].astype(np.int32)
        m.weights = skin[:, 8:].copy().view("<f4").reshape(vc, 4)
        bad_bone = m.bone_idx >= nbon
        if bad_bone.any():
            # 255 is used as "no bone" filler. Zero its weight rather than
            # binding the vertex to a bone that does not exist.
            if log:
                log.warn("mesh %d '%s': %d bone slots point past the bone list, "
                         "their weights are cleared", g, m.name,
                         int(bad_bone.sum()))
            m.weights = np.where(bad_bone, 0.0, m.weights)
            m.bone_idx = np.where(bad_bone, 0, m.bone_idx)

        if len(m.tris) == 0:
            if log:
                log.warn("mesh %d '%s' has no usable triangles, skipped",
                         g, m.name)
            continue
        model.meshes.append(m)
        if log and matidx >= max(t.get("nmtl", 0), 1):
            log.warn("mesh %d references material %d but the file lists only "
                     "%d", g, matidx, t.get("nmtl", 0))
        if log:
            ws = m.weights.sum(axis=1)
            log.info("mesh %d '%s': %d verts, %d tris, material %d",
                     g, m.name, vc, len(m.tris), matidx)
            log.info("   weight sums min %.5f max %.5f | normals |n| median "
                     "%.5f", ws.min(), ws.max(),
                     float(np.median(np.linalg.norm(m.normals, axis=1))))
            log.info("   bone index max %d (of %d bones) | uv %s .. %s",
                     int(m.bone_idx.max()), nbon,
                     np.round(m.uvs.min(axis=0), 3).tolist(),
                     np.round(m.uvs.max(axis=0), 3).tolist())

    # ---- actions (parsed above, logged here) -------------------------------
    for c in model.clips:
        if log:
            log.info("clip %-26s frames %4d..%-4d (%d)",
                     c.name, c.start, c.end, c.end - c.start + 1)
    if log and model.clips:
        mx = max(c.end for c in model.clips)
        log.info("clips: %d, highest frame %d of %d", len(model.clips), mx,
                 model.frames - 1)
        if mx >= model.frames:
            log.error("a clip runs past the end of the timeline!")
    return model


def _sanitise_tracks(model, log=None):
    """Replace NaN / infinite keys with the nearest valid frame.

    156_skin10.x has one bone out of 128 whose position and rotation are NaN
    for 37 consecutive frames. Every other quaternion in that file is exactly
    unit length, so this is corrupt data in the file, not a decoding error.
    Left alone a single NaN propagates through the whole skinned mesh.
    """
    fixed_bones = 0
    fixed_frames = 0
    for b in model.bones:
        arrays = [("pos", b.pos), ("quat", b.quat)]
        if b.scale is not None:
            arrays.append(("scale", b.scale))
        bad = np.zeros(len(b.pos), dtype=bool)
        for _n, a in arrays:
            bad |= ~np.isfinite(np.asarray(a)).all(axis=1)
        if not bad.any():
            continue
        good = np.nonzero(~bad)[0]
        if len(good) == 0:
            # Every frame of this bone is broken -- 144_skin8_huicheng.model
            # has one like that, and leaving it NaN collapses every vertex
            # weighted to it. Fall back to an identity transform.
            fixed_bones += 1
            fixed_frames += int(bad.sum())
            b.pos = np.zeros_like(np.asarray(b.pos))
            q = np.zeros_like(np.asarray(b.quat))
            q[:, 3] = 1.0
            b.quat = q
            if b.scale is not None:
                b.scale = np.ones_like(np.asarray(b.scale))
            continue
        fixed_bones += 1
        fixed_frames += int(bad.sum())
        src = good[np.clip(np.searchsorted(good, np.nonzero(bad)[0]), 0,
                           len(good) - 1)]
        for name, a in arrays:
            arr = np.array(a, copy=True)
            arr[bad] = arr[src]
            setattr(b, name, arr)
    if fixed_bones and log:
        log.warn("%d bone(s) contain NaN keys in %d frames (corrupt data in "
                 "the file); replaced with the nearest valid frame",
                 fixed_bones, fixed_frames)

    # A few files carry rotation keys that are not unit length -- 156_skin10.x
    # has 7 bones out of 128 with values down to exactly 0.5. The layout is
    # fine there (121 bones are exact and the block test scores 100%), so this
    # is source data, not a decoding error. Normalise instead of feeding a
    # scaled quaternion into the pose matrix.
    off_bones = off_keys = 0
    for b in model.bones:
        q = np.array(b.quat, dtype=np.float64, copy=True)
        ln = np.linalg.norm(q, axis=1)
        bad = np.abs(ln - 1.0) > 1e-3
        if not bad.any():
            continue
        off_bones += 1
        off_keys += int(bad.sum())
        q /= np.maximum(ln, 1e-9)[:, None]
        b.quat = q.astype(np.float32)
    if off_bones and log:
        log.warn("%d bone(s) have non-unit rotation keys in %d frames; "
                 "normalised", off_bones, off_keys)
    if log:
        left = 0
        for b in model.bones:
            left += int((~np.isfinite(np.asarray(b.pos)).all(axis=1)).sum())
            left += int((~np.isfinite(np.asarray(b.quat)).all(axis=1)).sum())
        if left:
            log.error("%d non-finite bone keys survived sanitising -- the "
                      "skinned mesh will collapse wherever they are used", left)
    return fixed_bones


def _solve_frames(sizes, addrs, B2, clips, log=None):
    """Work out the length of the shared timeline.

    A bone block is frames * bytesPerFrame with bytesPerFrame in
    BYTES_PER_FRAME, so several (frames, bytesPerFrame) pairs can be
    structurally valid for the same block size. 063_skin7.x has blocks of
    26720 bytes, which fits BOTH 835 frames at 32 bytes and 668 frames at 40 --
    and only the second one is real.

    Structure alone cannot decide that, so every candidate is CHECKED: the
    rotation track has to come out as unit quaternions. The wrong candidate
    scores 16.5% on 063_skin7.x, the right one 100.0%.
    """
    floor = max((c.end for c in clips), default=0) + 1
    smallest = min(sizes)
    results = []
    for bpf in BYTES_PER_FRAME:
        if smallest % bpf:
            continue
        f = smallest // bpf
        if f < floor:
            continue
        if not all(s % f == 0 and (s // f) in BYTES_PER_FRAME for s in sizes):
            continue
        good, dev = _unit_quaternion_score(addrs, B2, f)
        results.append((good, dev, f, bpf))
        if log:
            log.debug("frame count candidate %d (%d bytes per frame): "
                      "%.1f%% unit quaternions, median deviation %.6f",
                      f, bpf, 100.0 * good, dev)
    if not results:
        raise XParseError(
            "cannot determine the frame count: block sizes %s, clips need at "
            "least %d frames" % (sorted(set(sizes)), floor))
    # Rank by the MEDIAN deviation from unit length, not by the share of
    # exactly-unit keys. A correct candidate scores a median of 0.000000 even
    # when a handful of bones carry dirty rotations; the share drops to 88-98%
    # in that case and used to raise a false alarm on 21 files of the game's
    # roleaction folder. A wrong candidate lands at 0.014 or worse.
    results.sort(key=lambda r: (r[1], -r[0]))
    good, dev, f, bpf = results[0]
    if log and len(results) > 1:
        log.info("frame count: %d (%d bytes per frame, median deviation "
                 "%.6f, %.1f%% exactly unit); rejected %s", f, bpf, dev,
                 100.0 * good,
                 ", ".join("%d frames at deviation %.6f" % (r[2], r[1])
                           for r in results[1:]))
    if log:
        if dev > 0.005:
            log.error("best frame count %d still shows a median quaternion "
                      "deviation of %.6f (%.1f%% exactly unit) -- the bone "
                      "block layout is not understood for this file",
                      f, dev, 100.0 * good)
        elif good < 0.99:
            log.info("frame count %d: %.1f%% of rotation keys are exactly unit "
                     "length, the rest are dirty source data (median deviation "
                     "%.6f, well inside tolerance)", f, 100.0 * good, dev)
    return f


def _unit_quaternion_score(addrs, B2, frames, sample=24):
    """(share of exactly-unit keys, median deviation from unit length)."""
    devs = []
    step = max(1, len(addrs) // sample)
    for k in range(0, len(addrs), step):
        o = addrs[k] + frames * 12
        if o + frames * 16 > len(B2):
            continue
        q = np.frombuffer(B2, dtype="<f4", count=frames * 4,
                          offset=o).reshape(frames, 4).astype(np.float64)
        ln = np.linalg.norm(q, axis=1)
        ln = ln[np.isfinite(ln)]
        if len(ln):
            devs.append(np.abs(ln - 1.0))
    if not devs:
        return 0.0, 1.0
    d = np.concatenate(devs)
    return float((d < 1e-3).mean()), float(np.median(d))


def _mesh_region_end(B1, B2, tags, ngeo):
    """Byte offset in block 2 where the mesh data ends."""
    ageo = tags.get("ageo", 0)
    end = 0
    for g in range(ngeo):
        base = ageo + g * GEO_STRIDE
        vc, tc = struct.unpack_from("<II", B1, base + 28)
        addr = struct.unpack_from("<I", B1, base + 36)[0] - ADDR_BASE
        end = max(end, addr + vc * 12 + vc * 12 + vc * 8 + vc + tc * 6 + vc * 24)
    return end


def animation_rigidity(model, log=None, samples=4):
    """Skinning must be RIGID: every edge keeps its length in every pose.

    Report the MAXIMUM, not the median. A handful of torn edges leaves the
    median at 1.000 while the model visibly falls apart -- that is exactly how
    a conjugated quaternion hid here for a while.
    """
    if not model.meshes or not model.bones:
        return None
    if not model.clips:
        if log:
            log.info("animation rigidity: file has no clips, nothing to check")
        return None
    mesh = max(model.meshes, key=lambda m: len(m.verts))
    P = mesh.verts.astype(np.float64)
    h = np.concatenate([P, np.ones((len(P), 1))], axis=1)
    T = mesh.tris.astype(np.int64)
    E = np.unique(np.sort(np.concatenate(
        [T[:, [0, 1]], T[:, [1, 2]], T[:, [2, 0]]]), axis=1), axis=0)
    L0 = np.linalg.norm(P[E[:, 0]] - P[E[:, 1]], axis=1)
    I, W = mesh.bone_idx, mesh.weights.astype(np.float64)

    def mat(k, f):
        b = model.bones[k]
        q = b.quat[f]
        x, y, z, w = -float(q[0]), -float(q[1]), -float(q[2]), float(q[3])
        s = 2.0 / max(x * x + y * y + z * z + w * w, 1e-12)
        R = np.array([[1 - s * (y * y + z * z), s * (x * y - z * w), s * (x * z + y * w)],
                      [s * (x * y + z * w), 1 - s * (x * x + z * z), s * (y * z - x * w)],
                      [s * (x * z - y * w), s * (y * z + x * w), 1 - s * (x * x + y * y)]])
        if b.scale is not None:
            R = R @ np.diag(np.asarray(b.scale[f], dtype=np.float64))
        M = np.eye(4)
        M[:3, :3] = R
        M[:3, 3] = b.pos[f]
        return M

    IB = [np.linalg.inv(mat(k, 0)) for k in range(len(model.bones))]
    worst = 0.0
    worst_frac = 0.0
    worst_at = (None, 0)
    for clip in model.clips:
        n = max(1, clip.end - clip.start + 1)
        for j in range(samples):
            f = min(clip.start + (n - 1) * j // max(samples - 1, 1), model.frames - 1)
            v = np.zeros((len(P), 3))
            for k in range(len(model.bones)):
                Mx = mat(k, f) @ IB[k]
                for sl in range(4):
                    sel = (I[:, sl] == k) & (W[:, sl] > 1e-6)
                    if sel.any():
                        v[sel] += (h[sel] @ Mx.T)[:, :3] * W[sel, sl, None]
            L = np.linalg.norm(v[E[:, 0]] - v[E[:, 1]], axis=1)
            ratio = L / np.maximum(L0, 1e-9)
            # normalise by the frame's own median so a uniform scale animation
            # does not read as tearing (see eg3d_diag for the .model case)
            med = float(np.median(ratio))
            if med > 1e-6:
                ratio = ratio / med
            worst_frac = max(worst_frac, float((ratio > 3.0).mean()))
            r = float(np.max(ratio))
            if r > worst:
                worst, worst_at = r, (clip.name, f)
    if log:
        log.info("animation rigidity: worst edge stretch %.2fx (clip %r frame %d), "
                 "worst frame has %.2f%% of edges over 3x",
                 worst, worst_at[0], worst_at[1], 100.0 * worst_frac)
        # The FRACTION separates far better than the maximum. Measured on
        # 020_skin2.x with the wrong quaternion convention vs the right one:
        # max 23.2x vs 14.1x -- overlapping -- but 5.30% vs 0.38% of edges
        # over 3x, more than a factor of ten apart.
        _rigidity_verdict(worst_frac, log)
    return worst


def _rigidity_verdict(frac, log):
    if frac > 0.02:
        log.error("skinning is NOT rigid: %.2f%% of edges stretch past 3x. "
                  "Check the rotation convention and the bind frame "
                  "(a broken decode measures around 5%%).", 100.0 * frac)
    elif frac > 0.005:
        log.warn("skinning is borderline: %.2f%% of edges stretch past 3x "
                 "(healthy files measure under 0.5%%).", 100.0 * frac)
    else:
        log.info("  (that is fine: a few near-coincident vertices with opposite "
                 "weights always separate under linear blend skinning)")


def _would_cycle(model, parent, child):
    p = parent
    guard = 0
    while p >= 0 and guard < 512:
        if p == child:
            return True
        p = model.bones[p].parent
        guard += 1
    return False


def _parse_hierarchy(model, B1, log=None):
    """The bone name table doubles as the child list.

    Layout: [name NUL] followed by zero or more u32 child indices. A child
    index is identifiable because bytes 2..4 of the word are zero, which no
    ASCII name can produce.
    """
    n = len(model.bones)
    by_name = {}
    offs = []
    abon = model.tags.get("abon", 0)
    for k, b in enumerate(model.bones):
        base = abon + k * BONE_STRIDE
        try:
            noff = struct.unpack_from("<I", B1, base + BONE_NAME_FIELD)[0]
        except struct.error:
            continue
        if _cstr(B1, noff):
            offs.append((noff, k))
            by_name[b.name] = k
    links = 0
    for noff, k in offs:
        p = B1.find(b"\x00", noff)
        if p < 0:
            continue
        p += 1
        while p + 4 <= len(B1):
            w = B1[p:p + 4]
            if w[1] or w[2] or w[3]:
                break
            child = w[0]
            if child >= n:
                break
            if child == 0:
                # Four zero bytes are indistinguishable from "child index 0".
                # Index 0 is the alphabetically first name, which on a Biped
                # rig is the root, so treating this as padding is safe and
                # losing it costs nothing.
                break
            if _would_cycle(model, k, child):
                break
            model.bones[k].children.append(child)
            if model.bones[child].parent < 0:
                model.bones[child].parent = k
                links += 1
            p += 4
    if log:
        log.info("hierarchy: %d parent links recovered from the name table", links)


# ---------------------------------------------------------------------------
# standalone
# ---------------------------------------------------------------------------

class _Log(object):
    def __init__(self, v=False):
        self.v = v

    def _p(self, lvl, f, *a):
        try:
            m = f % a if a else f
        except Exception:
            m = "%s %s" % (f, a)
        print("[%-5s] %s" % (lvl, m))

    def info(self, f, *a):
        self._p("INFO", f, *a)

    def warn(self, f, *a):
        self._p("WARN", f, *a)

    def error(self, f, *a):
        self._p("ERROR", f, *a)

    def debug(self, f, *a):
        if self.v:
            self._p("DEBUG", f, *a)

    def trace(self, f, *a):
        if self.v:
            self._p("TRACE", f, *a)


if __name__ == "__main__":
    import sys
    args = [a for a in sys.argv[1:] if not a.startswith("-")]
    if not args:
        print(__doc__)
        raise SystemExit(1)
    lg = _Log("-v" in sys.argv or "--verbose" in sys.argv)
    mdl = parse_jumpx(args[0], log=lg)
    print("OK: %s  (%d meshes, %d bones, %d clips, %d frames)"
          % (os.path.basename(args[0]), len(mdl.meshes), len(mdl.bones),
             len(mdl.clips), mdl.frames))
