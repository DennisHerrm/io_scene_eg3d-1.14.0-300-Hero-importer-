# SPDX-License-Identifier: GPL-3.0-or-later
"""
Parser for the EG3D / ezgame ".model" format (game: 300 Heroes / 300英雄).

This module has NO bpy dependency on purpose -- you can run it standalone:

    python eg3d_parse.py path/to/157_skin11.model
    python eg3d_parse.py path/to/157_skin11.model --verbose

=============================================================================
 THE ONE THING THAT MATTERS  (read this before changing anything)
=============================================================================
Every offset stored in the JSON metadata is RELATIVE TO THE BINARY BLOCK,
and the binary block starts at file byte 12 (after 'EG3D' + u32 version +
u32 mainSize).

    absolute_file_offset = 12 + offset_from_json

Earlier reverse-engineering attempts treated those offsets as absolute file
offsets. That is off by exactly 12 bytes, and 12 bytes is:

    positions  6 bytes/vertex -> shifted by 2 vertices
    normals    4 bytes/vertex -> shifted by 3 vertices
    UV         4 bytes/vertex -> shifted by 3 vertices
    weights    8 bytes/vertex -> shifted by 1.5 vertices  (!! not integer)
    bones      4 bytes/vertex -> shifted by 3 vertices
    indices    2 bytes/index  -> shifted by 6 indices     (the "garbage header")
    quaternion 16 bytes       -> reads 12 bytes of the previous record

So the mesh gets rebuilt from vertices that belong to *other* vertices.
That is what produced, in previous attempts:
  * "bridge triangles" spanning the whole model
  * holes everywhere
  * a shattered / faceted look
  * bone quaternions with |q| = 0.14 instead of 1.0 -> skeleton "next to" mesh
  * skin weights that do not sum to 1
  * a 6-u16 "garbage header" at the start of every index buffer
  * a "hidden 12-byte header" in front of every animation value array
None of those things exist. They were all the same off-by-12.

With the correct base, every buffer chains byte-perfectly into the next one.
`verify_layout()` below proves that and is printed by the importer as a table.
=============================================================================
"""

import json
import os
import struct

try:
    import numpy as np
except Exception:  # pragma: no cover - Blender always ships numpy
    np = None

BLOCK_BASE = 12  # <-- the whole point. See docstring above.

# Component encodings used by attribute descriptors.
#   code: (numpy dtype, bytes per component, human name)
ATTR_TYPES = {
    0: ("<u1", 1, "uint8"),
    1: ("<u1", 1, "unorm8"),
    2: ("<u2", 2, "uint16"),
    3: ("<i1", 1, "int8"),
    4: ("<f2", 2, "float16"),
    5: ("<f2", 2, "float16"),
}

# Attribute ids (semantic slot), as used by meta[3] submesh descriptors.
ATTR_POSITION = 0
ATTR_NORMAL = 1      # 4 bytes/vertex: int16 height + int16 azimuth, see decode_normals
ATTR_TANGENT = 2     # float16 x4, xyz = unit tangent, w = handedness
ATTR_COLOR = 3       # uint8 x4 RGBA, normalise flag set (desc[4] == 1)
ATTR_BONES = 4       # uint8 x4, LOCAL index into the group's bone palette
ATTR_WEIGHTS = 5     # float16 x4
ATTR_UV = 6          # uint16 x2, dequantised

ATTR_NAMES = {
    0: "POSITION", 1: "NORMAL(z+azimuth)", 2: "TANGENT", 3: "COLOR",
    4: "BONE_INDICES", 5: "BONE_WEIGHTS", 6: "UV0", 7: "UV1",
}

# Animation channel kinds (channel[1]).
CH_LOCATION = 0
CH_ROTATION = 1
CH_SCALE = 2
CH_NAMES = {0: "location", 1: "rotation", 2: "scale"}


class ParseError(Exception):
    pass


# ---------------------------------------------------------------------------
# small helpers
# ---------------------------------------------------------------------------

def _u32(data, off):
    return struct.unpack_from("<I", data, off)[0]


def _f32v(data, off, n):
    return list(struct.unpack_from("<%df" % n, data, off))


class Model(object):
    """Everything decoded out of one .model file."""

    def __init__(self):
        self.path = ""
        self.filesize = 0
        self.version = 0
        self.main_size = 0
        self.header = {}
        self.meta = []
        self.materials = []      # list of dict(name, type, props)
        self.textures = []       # list of dict(uri, ...)
        self.groups = []         # list of list of Submesh
        self.palettes = []       # list of dict(bones=[node idx], bind=[4x4 row-major])
        self.nodes = []          # list of Node
        self.instances = []      # list of dict(group, node, palette)
        self.clips = []          # list of Clip
        self.layout = []         # list of layout records for verify_layout()

    # convenience
    def group_placement(self, group):
        """Where a geometry group is used, and with which bone palette."""
        return [inst for inst in self.instances if inst["group"] == group]

    def all_submeshes(self):
        out = []
        for gi, g in enumerate(self.groups):
            for sm in g:
                out.append((gi, sm))
        return out


class Submesh(object):
    def __init__(self):
        self.group = 0
        self.index_in_group = 0
        self.material = 0
        self.vertex_count = 0
        self.attrs = {}          # attr id -> decoded numpy array (float32)
        self.normals = None      # decoded unit normals from attribute 1
        self.attr_desc = {}      # attr id -> raw descriptor list
        self.raw = {}            # attr id -> raw (undecoded) numpy array
        self.indices = None      # numpy int32, flat
        self.triangles = None    # numpy int32 (n,3)
        self.idx_offset = 0
        self.idx_count = 0

    @property
    def name(self):
        return "g%d_s%d" % (self.group, self.index_in_group)


class Node(object):
    def __init__(self):
        self.index = 0
        self.name = ""
        self.translation = (0.0, 0.0, 0.0)
        self.rotation = (0.0, 0.0, 0.0, 1.0)   # x, y, z, w
        self.scale = (1.0, 1.0, 1.0)
        self.has_translation = False
        self.has_rotation = False
        self.has_scale = False
        self.children = []
        self.parent = -1
        self.mesh_group = None       # index into Model.groups if this is a mesh node
        self.raw = None

    def __repr__(self):
        return "<Node %d %r parent=%d>" % (self.index, self.name, self.parent)


class Clip(object):
    def __init__(self):
        self.name = ""
        self.channels = []       # list of Channel
        self.duration_ms = 0.0


class Channel(object):
    def __init__(self):
        self.node = 0
        self.kind = 0            # CH_LOCATION / CH_ROTATION / CH_SCALE
        self.key_count = 0
        self.components = 0
        self.times_ms = None     # numpy float64, absolute milliseconds
        self.values = None       # numpy float32 (key_count, components)


# ---------------------------------------------------------------------------
# container
# ---------------------------------------------------------------------------

def read_container(path, log=None):
    """Read file, split header / binary block / JSON tail."""
    if os.path.isdir(path):
        raise ParseError("%r is a folder, not a .model file" % path)
    if not os.path.isfile(path):
        raise ParseError("%r does not exist" % path)
    with open(path, "rb") as fh:
        data = fh.read()

    if len(data) < 16:
        raise ParseError("File too small to be an EG3D model (%d bytes)" % len(data))
    magic = data[0:4]
    if magic != b"EG3D":
        raise ParseError("Bad magic %r - expected b'EG3D'" % magic)

    version = _u32(data, 4)
    main_size = _u32(data, 8)
    json_start = 12 + main_size

    if log:
        log.info("container: size=%d  version=%d  mainSize=%d  jsonStart=%d",
                 len(data), version, main_size, json_start)

    if json_start >= len(data):
        raise ParseError("mainSize %d puts the JSON tail past EOF (%d)"
                         % (main_size, len(data)))

    tail = data[json_start:].decode("utf-8", errors="replace")
    try:
        meta, consumed = json.JSONDecoder().raw_decode(tail)
    except ValueError as exc:
        raise ParseError("JSON metadata is not parseable: %s" % exc)

    if log:
        log.info("json tail: %d chars, %d consumed, %d trailing bytes",
                 len(tail), consumed, len(tail) - consumed)
        if not isinstance(meta, list):
            log.warn("meta is %s, expected list", type(meta).__name__)
        else:
            log.info("meta has %d sections", len(meta))

    return data, meta, version, main_size


# ---------------------------------------------------------------------------
# attribute decoding
# ---------------------------------------------------------------------------

def decode_normals(raw):
    """Attribute 1 is a normal as HEIGHT + AZIMUTH, not a vector.

        int16 c0 -> z    = c0 / 16384        (15 bit, range -1..1)
        int16 c1 -> phi  = c1 / 32768 * pi   (16 bit, full circle)
        r = sqrt(1 - z*z)
        n = (-r*sin(phi), -z, -r*cos(phi))

    How it was found: bytes 1 and 3 are smooth across mesh edges while bytes
    0 and 2 are noise, which is the signature of two little-endian 16 bit
    values. Byte 1 then only ever takes 128 of 256 values -- exactly the
    patterns 00xxxxxx and 11xxxxxx, i.e. bit 7 always equals bit 6, which is
    a sign-extended 15 bit integer. One component needing 15 bits and the
    other 16 rules out an octahedral pair (both would need the same range)
    and points at an angle plus a height.

    Verified against area-weighted geometric normals: dot = +0.970 / +0.967 /
    +0.973 on the curved submeshes of 157_skin11.model and +1.000 on its flat
    card submesh, where the reference normal is exact. On 334.model +0.990,
    +0.986, +0.969, +0.973, +1.000. The decoded vectors are unit length to
    five decimals and sit at |dot| 0.004..0.15 against the stored tangent,
    i.e. perpendicular as a TBN frame requires.
    """
    i16 = np.ascontiguousarray(raw.astype(np.uint8)).view("<i2").reshape(-1, 2)
    z = i16[:, 0].astype(np.float64) / 16384.0
    phi = i16[:, 1].astype(np.float64) / 32768.0 * np.pi
    r = np.sqrt(np.maximum(0.0, 1.0 - z * z))
    n = np.stack([-r * np.sin(phi), -z, -r * np.cos(phi)], axis=1)
    return n / np.maximum(np.linalg.norm(n, axis=1, keepdims=True), 1e-9)


def _attr_stride(type_code, comps):
    """Bytes per vertex for one attribute.

    int8 / uint8 attributes are padded to 4 bytes per vertex even when only
    3 components are used (the 4th byte is padding / handedness).
    """
    dt, size, _ = ATTR_TYPES[type_code]
    if type_code in (0, 3) and comps < 4:
        return 4
    return comps * size


def decode_attribute(data, desc, vertex_count, log=None, sub_name=""):
    """Decode one attribute descriptor.

    desc = [attrId, typeCode, ?, components, 0, dataOffset, (scaleOffset, biasOffset)]
    Returns (decoded float32 array, raw array, info dict)
    """
    attr_id = desc[0]
    type_code = desc[1]
    comps = desc[3]
    off = BLOCK_BASE + desc[5]

    if type_code not in ATTR_TYPES:
        raise ParseError("unknown attribute type code %d for attr %d"
                         % (type_code, attr_id))
    dt, csize, tname = ATTR_TYPES[type_code]
    stride = _attr_stride(type_code, comps)
    cols = stride // csize

    need = off + stride * vertex_count
    if need > len(data):
        raise ParseError("attr %d (%s) runs past EOF: needs %d, file is %d"
                         % (attr_id, ATTR_NAMES.get(attr_id, "?"), need, len(data)))

    raw = np.frombuffer(data, dtype=dt, count=vertex_count * cols,
                        offset=off).reshape(vertex_count, cols)
    arr = raw[:, :comps].astype(np.float32)

    # desc[4] == 1 means "normalised integer": scale into 0..1 / -1..1
    normalised = len(desc) > 4 and desc[4] == 1
    if normalised:
        denom = {"<u1": 255.0, "<i1": 127.0, "<u2": 65535.0, "<i2": 32767.0}.get(dt)
        if denom:
            arr = arr / denom

    info = {
        "attr": attr_id,
        "name": ATTR_NAMES.get(attr_id, "ATTR%d" % attr_id),
        "type": tname,
        "components": comps,
        "stride": stride,
        "offset_json": desc[5],
        "offset_abs": off,
        "end_abs": off + stride * vertex_count,
        "normalised": normalised,
        "dequantised": False,
        "scale": None,
        "bias": None,
    }

    # positions and UVs are quantised: value = bias + raw * scale
    if len(desc) > 7 and desc[6] is not None and desc[7] is not None:
        so = BLOCK_BASE + desc[6]
        bo = BLOCK_BASE + desc[7]
        scale = _f32v(data, so, comps)
        bias = _f32v(data, bo, comps)
        arr = np.asarray(bias, dtype=np.float32) + arr * np.asarray(scale, dtype=np.float32)
        info["dequantised"] = True
        info["scale"] = scale
        info["bias"] = bias
        info["end_abs"] = bo + 4 * comps
        if log:
            log.trace("  %s/%s scale=%s bias=%s (scale@%d bias@%d)",
                      sub_name, info["name"],
                      ["%.3e" % s for s in scale], ["%.4f" % b for b in bias], so, bo)

    if log:
        log.debug("  %s/%-14s %-8s x%d  @%d..%d  stride=%d%s",
                  sub_name, info["name"], tname, comps,
                  info["offset_abs"], info["end_abs"], stride,
                  "  [dequantised]" if info["dequantised"] else "")
    return arr, raw, info


# ---------------------------------------------------------------------------
# geometry
# ---------------------------------------------------------------------------

def parse_geometry(model, data, log=None):
    meta3 = model.meta[3] if len(model.meta) > 3 else []
    for gi, group in enumerate(meta3):
        subs = []
        for si, desc in enumerate(group):
            sm = Submesh()
            sm.group = gi
            sm.index_in_group = si
            sm.material = desc[0]
            sm.vertex_count = desc[1]
            attr_list = desc[2]
            sm.idx_offset, sm.idx_count = desc[3]

            if log:
                log.info("submesh %s: material=%d verts=%d attrs=%d idx@%d count=%d",
                         sm.name, sm.material, sm.vertex_count,
                         len(attr_list), sm.idx_offset, sm.idx_count)

            for adesc in attr_list:
                arr, raw, info = decode_attribute(
                    data, adesc, sm.vertex_count, log=log, sub_name=sm.name)
                sm.attrs[adesc[0]] = arr
                sm.raw[adesc[0]] = raw
                sm.attr_desc[adesc[0]] = adesc
                if adesc[0] == ATTR_NORMAL:
                    sm.normals = decode_normals(raw)
                model.layout.append({
                    "owner": "%s.%s" % (sm.name, info["name"]),
                    "start": info["offset_abs"],
                    "end": info["end_abs"],
                })

            ioff = BLOCK_BASE + sm.idx_offset
            need = ioff + sm.idx_count * 2
            if need > len(data):
                raise ParseError("index buffer of %s runs past EOF (%d > %d)"
                                 % (sm.name, need, len(data)))
            idx = np.frombuffer(data, dtype="<u2",
                                count=sm.idx_count, offset=ioff).astype(np.int32)
            model.layout.append({
                "owner": "%s.INDICES" % sm.name,
                "start": ioff, "end": ioff + sm.idx_count * 2,
            })

            usable = (len(idx) // 3) * 3
            if usable != len(idx) and log:
                log.warn("  %s: index count %d is not a multiple of 3, dropping %d",
                         sm.name, len(idx), len(idx) - usable)
            sm.indices = idx
            sm.triangles = idx[:usable].reshape(-1, 3)

            # Sanity: with the correct BLOCK_BASE there is NO garbage header and
            # every index is in range. If this fires, the base is wrong again.
            bad = int((sm.triangles >= sm.vertex_count).sum())
            if bad:
                if log:
                    log.error("  %s: %d indices >= vertexCount (%d). "
                              "This is the classic symptom of a wrong buffer base!",
                              sm.name, bad, sm.vertex_count)
            elif log:
                log.info("  %s: %d triangles, max index %d / %d  [in range]",
                         sm.name, len(sm.triangles),
                         int(sm.triangles.max()) if len(sm.triangles) else -1,
                         sm.vertex_count - 1)
            subs.append(sm)
        model.groups.append(subs)


# ---------------------------------------------------------------------------
# bone palettes + inverse bind matrices
# ---------------------------------------------------------------------------

def parse_palettes(model, data, log=None):
    """meta[4] = [ [ [nodeIndex,...], byteOffsetOfBindMatrices ], ... ]

    One entry per geometry group. The byte offset points at a run of
    len(bones) 4x4 float32 matrices, 64 bytes each, ROW-VECTOR convention
    (translation lives in the last ROW), i.e. transpose to get a column
    vector matrix. Each matrix is the INVERSE BIND matrix of that bone.

    IMPORTANT: the bone indices inside the vertex BONE_INDICES attribute are
    LOCAL indices into this palette, not global node indices.
    """
    meta4 = model.meta[4] if len(model.meta) > 4 else []
    for gi, entry in enumerate(meta4):
        bones, boff = entry[0], entry[1]
        base = BLOCK_BASE + boff
        mats = []
        for li in range(len(bones)):
            o = base + 64 * li
            if o + 64 > len(data):
                raise ParseError("bind matrix %d of palette %d past EOF" % (li, gi))
            m = list(struct.unpack_from("<16f", data, o))
            mats.append([m[0:4], m[4:8], m[8:12], m[12:16]])
        model.palettes.append({"bones": list(bones), "bind": mats,
                               "offset": base, "end": base + 64 * len(bones)})
        model.layout.append({"owner": "palette%d.BINDMATRICES" % gi,
                             "start": base, "end": base + 64 * len(bones)})
        if log:
            log.info("palette %d: %d bones, bind matrices @%d..%d",
                     gi, len(bones), base, base + 64 * len(bones))
            log.trace("  bones: %s", bones)


# ---------------------------------------------------------------------------
# node tree
# ---------------------------------------------------------------------------

def parse_nodes(model, data, log=None):
    """meta[5] = list of nodes.

    node = [name, translationOffset, rotationOffset, scaleOffset, ?,
            children, ?, ?, extras, flags]

    translation = 3 x float32   (12 bytes)   -- None means (0,0,0)
    rotation    = 4 x float32   (16 bytes)   -- x, y, z, w. None means identity
    scale       = 3 x float32   (12 bytes)   -- None means (1,1,1)

    NOTE: these transforms are NOT the bind pose. They are frame 0 of the
    autoPlay clip. The real bind pose lives in the inverse bind matrices of
    meta[4]. (Verified: node values are byte-identical to the first key of
    clip 'bat_idle'.)
    """
    meta5 = model.meta[5] if len(model.meta) > 5 else []
    bad_quat = 0
    for i, nd in enumerate(meta5):
        n = Node()
        n.index = i
        n.raw = nd
        n.name = nd[0] if nd and isinstance(nd[0], str) else "node_%d" % i

        t_off = nd[1] if len(nd) > 1 else None
        r_off = nd[2] if len(nd) > 2 else None
        s_off = nd[3] if len(nd) > 3 else None

        if isinstance(t_off, int):
            n.translation = tuple(_f32v(data, BLOCK_BASE + t_off, 3))
            n.has_translation = True
        if isinstance(r_off, int):
            q = _f32v(data, BLOCK_BASE + r_off, 4)
            ln = (q[0] * q[0] + q[1] * q[1] + q[2] * q[2] + q[3] * q[3]) ** 0.5
            if abs(ln - 1.0) > 0.02:
                bad_quat += 1
                if log:
                    log.warn("node %d %r: |q| = %.4f (expected 1.0) -> "
                             "buffer base is probably wrong", i, n.name, ln)
            n.rotation = tuple(q)
            n.has_rotation = True
        if isinstance(s_off, int):
            s = _f32v(data, BLOCK_BASE + s_off, 3)
            # sanity filter: a degenerate scale breaks matrix inversion
            if all(0.01 < abs(v) < 100.0 for v in s):
                n.scale = tuple(s)
                n.has_scale = True
            elif log:
                log.warn("node %d %r: implausible scale %s, using (1,1,1)",
                         i, n.name, s)

        ch = nd[5] if len(nd) > 5 else None
        n.children = list(ch) if isinstance(ch, list) else []
        if len(nd) > 6 and isinstance(nd[6], int):
            n.mesh_group = nd[6]
        model.nodes.append(n)

    for n in model.nodes:
        for c in n.children:
            if 0 <= c < len(model.nodes):
                model.nodes[c].parent = n.index

    # A mesh node names its geometry group in field 6 and, when the mesh is
    # skinned, its bone palette in field 7. The two are NOT interchangeable:
    # 039_skin8.model has 27 groups but only 7 palettes, and indexing the
    # palette by group number leaves 20 submeshes without any skinning.
    # A group can also appear at SEVERAL nodes -- that file instances the same
    # weapon mesh twice.
    for i, nd in enumerate(model.meta[5] if len(model.meta) > 5 else []):
        g = nd[6] if len(nd) > 6 else None
        pal = nd[7] if len(nd) > 7 else None
        if isinstance(g, int) and 0 <= g < len(model.groups):
            model.instances.append({
                "group": g, "node": i,
                "palette": pal if isinstance(pal, int) else None})

    if log:
        placed = {inst["group"] for inst in model.instances}
        skinned = sum(1 for inst in model.instances if inst["palette"] is not None)
        log.info("geometry: %d group(s), %d placed at %d node(s) (%d skinned, "
                 "%d rigid), %d not referenced by any node",
                 len(model.groups), len(placed), len(model.instances), skinned,
                 len(model.instances) - skinned, len(model.groups) - len(placed))
        multi = [g for g in placed if len(model.group_placement(g)) > 1]
        if multi:
            log.info("geometry: group(s) %s are instanced more than once", multi)

    if log:
        roots = [n.index for n in model.nodes if n.parent < 0]
        log.info("nodes: %d total, %d root(s) %s, %d bad quaternions",
                 len(model.nodes), len(roots), roots[:8], bad_quat)
    return bad_quat


# ---------------------------------------------------------------------------
# animation clips
# ---------------------------------------------------------------------------

def parse_clips(model, data, log=None):
    """meta[7] = [ [clipName, [channel, ...]], ... ]

    channel = [nodeIndex, kind, 0, keyCount, components,
               [timesOffset, timesType], [valuesOffset, valuesType]]

    times  : uint16 x keyCount -- DELTAS in milliseconds, first entry 0.
             Typical values are 33 / 66 / 100 ... i.e. multiples of 1/30 s.
    values : float32 x components x keyCount
    """
    meta7 = model.meta[7] if len(model.meta) > 7 else []
    for ci, cd in enumerate(meta7):
        clip = Clip()
        clip.name = cd[0] if isinstance(cd[0], str) else "clip_%d" % ci
        for chd in cd[1]:
            ch = Channel()
            ch.node = chd[0]
            ch.kind = chd[1]
            ch.key_count = chd[3]
            ch.components = chd[4]
            t_off = BLOCK_BASE + chd[5][0]
            v_off = BLOCK_BASE + chd[6][0]
            if v_off + ch.key_count * ch.components * 4 > len(data):
                if log:
                    log.warn("clip %r channel node=%d: values past EOF, skipped",
                             clip.name, ch.node)
                continue
            deltas = np.frombuffer(data, dtype="<u2",
                                   count=ch.key_count, offset=t_off).astype(np.float64)
            ch.times_ms = np.cumsum(deltas)
            ch.values = np.frombuffer(
                data, dtype="<f4", count=ch.key_count * ch.components,
                offset=v_off).reshape(ch.key_count, ch.components).astype(np.float32)
            clip.channels.append(ch)
            if ch.times_ms.size:
                clip.duration_ms = max(clip.duration_ms, float(ch.times_ms[-1]))
        model.clips.append(clip)
        if log:
            log.info("clip %-22s %3d channels  %.0f ms",
                     clip.name, len(clip.channels), clip.duration_ms)


# ---------------------------------------------------------------------------
# layout verification -- the diagnostic that would have caught the off-by-12
# ---------------------------------------------------------------------------

def verify_layout(model, data, log=None):
    """Every buffer must end exactly where the next one begins.

    With the correct BLOCK_BASE the gaps are 0 everywhere. A constant non-zero
    gap means the base offset is wrong.
    """
    recs = sorted(model.layout, key=lambda r: r["start"])
    gaps = []
    rows = []
    prev = None
    for r in recs:
        gap = None if prev is None else r["start"] - prev["end"]
        rows.append((r["owner"], r["start"], r["end"], gap))
        if gap is not None:
            gaps.append(gap)
        prev = r
    if log:
        log.info("---- buffer layout (%d blocks) ----", len(rows))
        log.info("%-34s %10s %10s %8s", "block", "start", "end", "gap")
        for owner, s, e, g in rows:
            log.info("%-34s %10d %10d %8s", owner, s, e,
                     "-" if g is None else str(g))
        if gaps:
            nz = [g for g in gaps if g != 0]
            log.info("gaps: %d blocks, %d non-zero, max=%d",
                     len(gaps), len(nz), max(gaps) if gaps else 0)
            if nz and all(g == nz[0] for g in nz) and len(nz) > 3:
                log.error("EVERY gap is %d bytes -> your buffer base is off by %d!",
                          nz[0], nz[0])
    return rows


# ---------------------------------------------------------------------------
# top level
# ---------------------------------------------------------------------------

def parse_model(path, log=None):
    if np is None:
        raise ParseError("numpy is required and was not importable")

    model = Model()
    model.path = path
    data, meta, version, main_size = read_container(path, log=log)
    model.filesize = len(data)
    model.version = version
    model.main_size = main_size
    model.meta = meta

    if isinstance(meta, list) and meta and isinstance(meta[0], dict):
        model.header = meta[0]
    if log:
        log.info("header: %s", model.header)

    if len(meta) > 2 and isinstance(meta[2], list):
        for m in meta[2]:
            model.materials.append({
                "name": m[0] if len(m) > 0 else "material",
                "type": m[1] if len(m) > 1 else "",
                "props": m[2] if len(m) > 2 else {},
            })
    if len(meta) > 6 and isinstance(meta[6], list):
        model.textures = list(meta[6])

    if log:
        for i, m in enumerate(model.materials):
            log.info("material %d: %-28s type=%-12s textures=%s",
                     i, m["name"], m["type"], m["props"].get("textures", {}))
        for i, t in enumerate(model.textures):
            log.info("texture  %d: %s", i, t.get("uri") if isinstance(t, dict) else t)

    parse_geometry(model, data, log=log)
    parse_palettes(model, data, log=log)
    parse_nodes(model, data, log=log)
    parse_clips(model, data, log=log)
    verify_layout(model, data, log=log)
    return model


# ---------------------------------------------------------------------------
# standalone CLI
# ---------------------------------------------------------------------------

class _StdoutLog(object):
    def __init__(self, verbose=False):
        self.verbose = verbose

    def _p(self, lvl, fmt, *a):
        try:
            msg = fmt % a if a else fmt
        except Exception:
            msg = "%s %s" % (fmt, a)
        print("[%-5s] %s" % (lvl, msg))

    def info(self, f, *a):
        self._p("INFO", f, *a)

    def warn(self, f, *a):
        self._p("WARN", f, *a)

    def error(self, f, *a):
        self._p("ERROR", f, *a)

    def debug(self, f, *a):
        if self.verbose:
            self._p("DEBUG", f, *a)

    def trace(self, f, *a):
        if self.verbose:
            self._p("TRACE", f, *a)


if __name__ == "__main__":
    import sys
    args = [a for a in sys.argv[1:] if not a.startswith("-")]
    verbose = "--verbose" in sys.argv or "-v" in sys.argv
    if not args:
        print(__doc__)
        print("usage: python eg3d_parse.py <file.model> [--verbose]")
        raise SystemExit(1)
    lg = _StdoutLog(verbose)
    mdl = parse_model(args[0], log=lg)
    try:
        from eg3d_diag import report
        report(mdl, log=lg)
    except Exception as exc:  # pragma: no cover
        print("(diagnostics unavailable: %s)" % exc)
    print("OK: %s" % os.path.basename(args[0]))
