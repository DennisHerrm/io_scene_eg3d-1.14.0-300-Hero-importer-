# SPDX-License-Identifier: GPL-3.0-or-later
"""Turn a parsed EG3D Model into Blender data blocks."""

import os

import bpy
import numpy as np
from mathutils import Matrix, Quaternion, Vector

try:
    from .eg3d_parse import (ATTR_POSITION, ATTR_NORMAL, ATTR_TANGENT,
                             ATTR_COLOR, ATTR_BONES, ATTR_WEIGHTS, ATTR_UV,
                             CH_LOCATION, CH_ROTATION, CH_SCALE, CH_NAMES)
except (ImportError, ValueError):  # pragma: no cover
    from eg3d_parse import (ATTR_POSITION, ATTR_NORMAL, ATTR_TANGENT,
                            ATTR_COLOR, ATTR_BONES, ATTR_WEIGHTS, ATTR_UV,
                            CH_LOCATION, CH_ROTATION, CH_SCALE, CH_NAMES)

TEXTURE_EXTS = (".dds", ".png", ".tga", ".tif", ".jpg", ".bmp")


# ---------------------------------------------------------------------------
# matrices
# ---------------------------------------------------------------------------

def bind_to_matrix(rows):
    """Inverse bind matrix -> mathutils.Matrix (column-vector convention).

    The file stores it row-vector style (translation in the LAST ROW), which
    is the DirectX / 3ds Max convention. Transpose to get Blender's.
    """
    return Matrix(rows).transposed()


def node_local_matrix(node):
    m = Quaternion((node.rotation[3], node.rotation[0],
                    node.rotation[1], node.rotation[2])).to_matrix().to_4x4()
    if node.has_scale:
        m = m @ Matrix.Diagonal(Vector(node.scale)).to_4x4()
    m.translation = Vector(node.translation)
    return m


def trs_matrix(loc, quat_xyzw, scale):
    m = Quaternion((quat_xyzw[3], quat_xyzw[0],
                    quat_xyzw[1], quat_xyzw[2])).to_matrix().to_4x4()
    if scale is not None:
        m = m @ Matrix.Diagonal(Vector(scale)).to_4x4()
    m.translation = Vector(loc)
    return m


# ---------------------------------------------------------------------------
# skeleton selection + rest pose
# ---------------------------------------------------------------------------

def collect_bone_nodes(model, only_skinned, log):
    """Which nodes become bones.

    Default: every node referenced by a bone palette, plus all of its
    ancestors. That automatically drops mesh instance nodes and effect
    attachment points, which use a different local axis convention and
    otherwise stick out of the model sideways.
    """
    skinned = set()
    for pal in model.palettes:
        for b in pal["bones"]:
            if 0 <= b < len(model.nodes):
                skinned.add(b)
    if not only_skinned:
        wanted = set(range(len(model.nodes)))
        mesh_nodes = set()
        for n in model.nodes:
            if n.mesh_group is not None and n.parent >= 0:
                mesh_nodes.add(n.index)
        wanted -= mesh_nodes
        log.info("skeleton: importing all %d nodes (minus %d mesh instances)",
                 len(model.nodes), len(mesh_nodes))
        return wanted, skinned

    wanted = set(skinned)
    for b in list(skinned):
        p = model.nodes[b].parent
        guard = 0
        while p >= 0 and p not in wanted and guard < 512:
            wanted.add(p)
            p = model.nodes[p].parent
            guard += 1
    # a root that carries no transform and no skinning is scene clutter
    log.info("skeleton: %d skinned bones + ancestors = %d nodes",
             len(skinned), len(wanted))
    return wanted, skinned


def build_rest_matrices(model, wanted, log):
    """Rest (bind) world matrix per node index.

    Bones with an inverse bind matrix get the exact bind pose. The rest are
    chained from their parent with their node local transform -- those are
    unskinned helpers, so nothing depends on their exact placement, but the
    log says so explicitly.
    """
    bind = {}
    for pal in model.palettes:
        for li, b in enumerate(pal["bones"]):
            if b in bind:
                continue
            bind[b] = bind_to_matrix(pal["bind"][li]).inverted_safe()

    rest = {}
    approximated = []
    order = []
    seen = set()

    def visit(i):
        if i in seen:
            return
        seen.add(i)
        order.append(i)
        for c in model.nodes[i].children:
            if 0 <= c < len(model.nodes):
                visit(c)

    for n in model.nodes:
        if n.parent < 0:
            visit(n.index)
    for n in model.nodes:
        visit(n.index)

    for i in order:
        n = model.nodes[i]
        if i in bind:
            rest[i] = bind[i]
        else:
            p = n.parent
            base = rest.get(p, Matrix.Identity(4))
            rest[i] = base @ node_local_matrix(n)
            if i in wanted:
                approximated.append(n.name)

    if approximated:
        log.warn("skeleton: %d bone(s) have no inverse-bind matrix, their rest "
                 "pose is chained from the parent (unskinned helpers): %s",
                 len(approximated), ", ".join(approximated[:12]) +
                 (" ..." if len(approximated) > 12 else ""))
    log.info("skeleton: %d bind matrices available", len(bind))
    return rest, bind


def node_world_matrices(model, locals_by_node):
    """Compose node local matrices into world matrices (node/animation space)."""
    world = {}

    def get(i):
        if i in world:
            return world[i]
        n = model.nodes[i]
        m = locals_by_node.get(i)
        if m is None:
            m = node_local_matrix(n)
        if n.parent >= 0:
            m = get(n.parent) @ m
        world[i] = m
        return m

    for i in range(len(model.nodes)):
        get(i)
    return world


# ---------------------------------------------------------------------------
# armature
# ---------------------------------------------------------------------------

def fcurve_count(action):
    """Count F-curves in an action across Blender versions.

    Blender 4.4 moved action data into layers, strips and channel bags. The
    legacy `action.fcurves` still works for simple actions, but reporting a
    real number matters here: if it ever comes back 0 while keyframes were
    inserted, the keys went somewhere the Dope Sheet will not show.
    """
    n = len(getattr(action, "fcurves", ()) or ())
    if n:
        return n
    try:
        for layer in action.layers:
            for strip in layer.strips:
                for bag in getattr(strip, "channelbags", ()):
                    n += len(bag.fcurves)
    except Exception:
        pass
    return n


def _finish_actions(context, arm_obj, made, opts, log, end_frame):
    """Assign the first clip, or leave the armature in its bind pose.

    An assigned action makes Blender show the POSE, so the bind pose looks
    "gone" right after import. Leaving it unassigned is the friendlier default;
    every clip is kept with a fake user either way.
    """
    context.scene.frame_start = 1
    if opts.get("assign_action"):
        arm_obj.animation_data.action = made[0]
        context.scene.frame_end = end_frame
        log.info("assigned action %r; the armature now shows that POSE. Switch "
                 "Object Data Properties > Skeleton to 'Rest Position' to see "
                 "the bind pose.", made[0].name)
    else:
        arm_obj.animation_data.action = None
        log.info("%d actions imported, none assigned -- the armature stays in "
                 "its bind pose. Pick a clip in the Action Editor (they are all "
                 "kept via fake user).", len(made))
    log.info("keyframes live on the POSE BONES: in the Dope Sheet, turn off "
             "'Only Show Selected' or enter Pose Mode and press A, otherwise "
             "the channel list looks empty.")


def _tidy_armature(arm_obj, log):
    """Draw bones as thin sticks and never in front of the mesh.

    Octahedral bones drawn over the geometry look like flat grey spikes
    sticking out of the model, which is easy to mistake for broken polygons.
    """
    try:
        arm_obj.show_in_front = False
        arm_obj.data.display_type = "STICK"
    except Exception as exc:
        log.debug("armature display not settable: %s", exc)


def auto_bone_size(opts, extent, log):
    """A fixed default length is wrong for one of the two formats: .model
    files are about 3 units tall, .x files about 128. Scale it instead."""
    if opts["bone_size"] > 0.0:
        return opts["bone_size"]
    size = max(float(extent), 1e-6) * 0.02
    log.info("bone length: automatic, %.4f (2%% of the model size %.3f)",
             size, extent)
    return size


def create_armature(context, model, opts, log):
    wanted, skinned = collect_bone_nodes(model, opts["only_skinned_bones"], log)
    rest, bind = build_rest_matrices(model, wanted, log)

    arm = bpy.data.armatures.new(opts["basename"] + "_Armature")
    arm_obj = bpy.data.objects.new(opts["basename"] + "_Armature", arm)
    context.collection.objects.link(arm_obj)

    ext = 1.0
    try:
        allp = np.concatenate([sm.attrs[ATTR_POSITION]
                               for _, sm in model.all_submeshes()
                               if ATTR_POSITION in sm.attrs])
        ext = float(np.linalg.norm(allp.max(axis=0) - allp.min(axis=0)))
    except Exception:
        pass
    bsize = auto_bone_size(opts, ext, log)

    view = context.view_layer
    view.objects.active = arm_obj
    arm_obj.select_set(True)
    bpy.ops.object.mode_set(mode="EDIT")

    xform = opts["xform"]
    mirror = opts["mirror"]
    names = {}
    try:
        order = sorted(wanted)
        for i in order:
            n = model.nodes[i]
            base = n.name or "bone_%d" % i
            nm = base
            k = 1
            while nm in arm.edit_bones:
                nm = "%s.%03d" % (base, k)
                k += 1
            eb = arm.edit_bones.new(nm)
            names[i] = eb.name

            # Mirroring a transform is a CONJUGATION (Mir @ B @ Mir), not a
            # left multiplication: that keeps the determinant at +1 so the
            # result is still a rotation and the bone axes stay valid.
            world = xform @ rest[i] @ mirror
            m = world.to_quaternion().to_matrix().to_4x4()
            m.translation = world.translation
            # bone length: reach for the first wanted child, else a default
            length = bsize
            # Use the NEAREST child, not the first one in the list. Picking an
            # arbitrary child makes bones shoot across the model and poke out
            # through the mesh, which reads as broken geometry in the viewport.
            kids = [c for c in n.children if c in wanted]
            if kids:
                ds = [((xform @ rest[c] @ mirror).translation - m.translation).length
                      for c in kids]
                ds = [v for v in ds if v > 1e-5]
                if ds:
                    length = min(ds)
            elif n.parent in rest:
                d = m.translation - (xform @ rest[n.parent] @ mirror).translation
                if d.length > 1e-5:
                    length = max(d.length * 0.4, 1e-4)
            eb.head = (0.0, 0.0, 0.0)
            eb.tail = (0.0, max(length, 1e-4), 0.0)
            eb.matrix = m
            eb.length = max(length, 1e-4)

        for i in order:
            p = model.nodes[i].parent
            if p in names:
                arm.edit_bones[names[i]].parent = arm.edit_bones[names[p]]
    finally:
        bpy.ops.object.mode_set(mode="OBJECT")

    _tidy_armature(arm_obj, log)
    log.info("armature '%s': %d bones created", arm_obj.name, len(names))
    return arm_obj, names, rest, bind, skinned


# ---------------------------------------------------------------------------
# materials
# ---------------------------------------------------------------------------

def find_texture(uri, search_dirs, log):
    if not uri:
        return None
    stem = os.path.splitext(os.path.basename(uri))[0]
    for d in search_dirs:
        if not d or not os.path.isdir(d):
            continue
        for ext in TEXTURE_EXTS:
            p = os.path.join(d, stem + ext)
            if os.path.isfile(p):
                return p
        try:
            low = {f.lower(): f for f in os.listdir(d)}
        except OSError:
            continue
        for ext in TEXTURE_EXTS:
            f = low.get((stem + ext).lower())
            if f:
                return os.path.join(d, f)
    log.warn("texture %r not found in: %s", uri,
             ", ".join(d for d in search_dirs if d))
    return None


def create_material(model, mat_index, opts, log, cache):
    if mat_index in cache:
        return cache[mat_index]
    if mat_index >= len(model.materials):
        m = bpy.data.materials.new("%s_mat%d" % (opts["basename"], mat_index))
        cache[mat_index] = m
        return m

    src = model.materials[mat_index]
    mat = bpy.data.materials.new(src["name"] or "material")
    mat.use_nodes = True
    nt = mat.node_tree
    bsdf = nt.nodes.get("Principled BSDF")
    if bsdf:
        try:
            bsdf.inputs["Roughness"].default_value = 0.6
            bsdf.inputs["Metallic"].default_value = 0.0
        except Exception:
            pass

    props = src.get("props") or {}
    tex_slot = (props.get("textures") or {}).get("_MainTex")
    img_path = None
    if isinstance(tex_slot, int) and tex_slot < len(model.textures):
        entry = model.textures[tex_slot]
        uri = entry.get("uri") if isinstance(entry, dict) else entry
        img_path = find_texture(uri, opts["texture_dirs"], log)
        log.info("material %d %-26s texture=%s -> %s",
                 mat_index, src["name"], uri, img_path or "NOT FOUND")

    if img_path and bsdf:
        try:
            img = bpy.data.images.load(img_path, check_existing=True)
            tex = nt.nodes.new("ShaderNodeTexImage")
            tex.image = img
            tex.location = (-420, 260)
            nt.links.new(tex.outputs["Color"], bsdf.inputs["Base Color"])
            nt.links.new(tex.outputs["Alpha"], bsdf.inputs["Alpha"])
        except Exception as exc:
            log.warn("could not load image %s: %s", img_path, exc)

    cutoff = props.get("_Cutoff")
    blend = props.get("blendMode", 0)
    for attr, val in (("blend_method", "CLIP" if blend == 0 else "BLEND"),
                      ("shadow_method", "CLIP" if blend == 0 else "NONE"),
                      ("alpha_threshold", float(cutoff) if cutoff else 0.5),
                      ("use_backface_culling", not props.get("doubleSide", 0))):
        try:
            setattr(mat, attr, val)
        except Exception:
            pass  # property removed / renamed in this Blender version

    cache[mat_index] = mat
    return mat


# ---------------------------------------------------------------------------
# mesh
# ---------------------------------------------------------------------------

def build_submesh(context, model, sm, opts, log, mat_cache, name_suffix=""):
    name = "%s_%s%s" % (opts["basename"], sm.name, name_suffix)
    pos = sm.attrs.get(ATTR_POSITION)
    tris = sm.triangles
    if pos is None or tris is None or len(tris) == 0:
        log.warn("%s: no geometry, skipped", name)
        return None

    xform = opts["xform"]
    P = pos.astype(np.float64)
    M = np.array(xform.to_3x3())
    T = np.array(xform.translation)
    P = P @ M.T + T

    # xform already contains the mirror when one was requested; a negative
    # determinant flips the orientation by itself, so the winding is only
    # reversed when the user asked for the winding-only correction.
    faces = tris[:, ::-1] if opts["flip_faces"] else tris

    me = bpy.data.meshes.new(name)
    me.from_pydata([tuple(v) for v in P], [], [tuple(int(i) for i in f) for f in faces])
    me.update()

    if len(me.polygons) != len(faces):
        log.error("%s: Blender kept only %d of %d faces -- duplicate or "
                  "degenerate triangles were rejected",
                  name, len(me.polygons), len(faces))

    # ---- UV ---------------------------------------------------------------
    uv = sm.attrs.get(ATTR_UV)
    if uv is not None and np.isfinite(uv).all():
        uvs = uv.astype(np.float64).copy()
        if opts["flip_uv_v"]:
            uvs[:, 1] = 1.0 - uvs[:, 1]
        layer = me.uv_layers.new(name="UVMap")
        try:
            loop_v = np.empty(len(me.loops), dtype=np.int32)
            me.loops.foreach_get("vertex_index", loop_v)
            layer.data.foreach_set(
                "uv", np.ascontiguousarray(uvs[loop_v], dtype=np.float32).ravel())
        except Exception as exc:
            log.warn("%s: fast UV path failed (%s), falling back to the slow one",
                     name, exc)
            for i, loop in enumerate(me.loops):
                layer.data[i].uv = uvs[loop.vertex_index]
        log.debug("%s: UV layer written (%d loops, V flipped=%s)",
                  name, len(me.loops), opts["flip_uv_v"])

    # ---- colour / raw attribute 1 ----------------------------------------
    col = sm.attrs.get(ATTR_COLOR)
    if col is not None and opts["import_colors"]:
        try:
            ca = me.color_attributes.new(name="Color", type="FLOAT_COLOR",
                                         domain="POINT")
            data = np.ones((sm.vertex_count, 4), dtype=np.float32)
            data[:, :col.shape[1]] = col
            ca.data.foreach_set("color", np.ascontiguousarray(data).ravel())
        except Exception as exc:
            log.warn("%s: colour attribute failed: %s", name, exc)

    if opts["debug_attributes"]:
        raw1 = sm.raw.get(ATTR_NORMAL)
        if raw1 is not None:
            try:
                ca = me.color_attributes.new(name="EG3D_attr1_raw",
                                             type="FLOAT_COLOR", domain="POINT")
                d = np.zeros((sm.vertex_count, 4), dtype=np.float32)
                v = raw1.astype(np.float32)
                d[:, :min(4, v.shape[1])] = (v[:, :4] / 255.0 + 0.5) % 1.0
                ca.data.foreach_set("color", np.ascontiguousarray(d).ravel())
                log.debug("%s: attribute 1 stored raw as 'EG3D_attr1_raw'", name)
            except Exception as exc:
                log.warn("%s: raw attr1 layer failed: %s", name, exc)

    # ---- shading ----------------------------------------------------------
    smooth = opts["normals"] != "FLAT"
    try:
        me.polygons.foreach_set("use_smooth", [smooth] * len(me.polygons))
    except Exception as exc:  # property renamed in a future Blender
        log.debug("%s: use_smooth not settable (%s), falling back", name, exc)
        try:
            me.shade_smooth() if smooth else me.shade_flat()
        except Exception:
            pass

    if opts["normals"] == "FILE" and getattr(sm, "normals", None) is not None:
        # Attribute 1 is a height + azimuth encoded unit normal; see
        # eg3d_parse.decode_normals for how that was established.
        n = sm.normals.astype(np.float64) @ M.T
        n = n / np.maximum(np.linalg.norm(n, axis=1, keepdims=True), 1e-9)
        if opts["flip_faces"]:
            n = -n
        try:
            me.normals_split_custom_set_from_vertices([tuple(v) for v in n])
            log.info("%s: custom split normals from the file", name)
        except Exception as exc:
            log.warn("%s: custom normals rejected: %s", name, exc)

    me.validate(verbose=False, clean_customdata=False)
    me.update()

    obj = bpy.data.objects.new(name, me)
    context.collection.objects.link(obj)
    mat = create_material(model, sm.material, opts, log, mat_cache)
    me.materials.append(mat)

    log.info("%s: %d verts, %d faces, material '%s'",
             name, len(me.vertices), len(me.polygons), mat.name)
    return obj


def apply_skinning(obj, model, sm, bone_names, log, palette_index=None):
    """Vertex groups from BONE_INDICES / BONE_WEIGHTS.

    BONE_INDICES are LOCAL indices into the palette of this submesh's group.
    Treating them as global node indices silently attaches the mesh to the
    wrong bones -- it looks fine at rest and explodes as soon as you play an
    animation.
    """
    idx = sm.attrs.get(ATTR_BONES)
    w = sm.attrs.get(ATTR_WEIGHTS)
    if idx is None or w is None:
        log.warn("%s: no skinning data", obj.name)
        return 0
    pi = sm.group if palette_index is None else palette_index
    if pi is None or pi >= len(model.palettes):
        log.error("%s: no bone palette (index %s of %d)", obj.name, pi,
                  len(model.palettes))
        return 0

    palette = model.palettes[pi]["bones"]
    idx = idx.astype(np.int64)
    w = w.astype(np.float64)

    out_of_range = int((idx >= len(palette)).sum())
    if out_of_range:
        log.error("%s: %d bone indices exceed the palette size (%d) -- "
                  "indices are palette-LOCAL, check the group mapping",
                  obj.name, out_of_range, len(palette))
        idx = np.clip(idx, 0, len(palette) - 1)

    total = w.sum(axis=1, keepdims=True)
    w = np.divide(w, np.where(total > 1e-8, total, 1.0))

    groups = {}
    assigned = 0
    for slot in range(idx.shape[1]):
        bl = idx[:, slot]
        ww = w[:, slot]
        keep = ww > 1e-5
        if not keep.any():
            continue
        for local in np.unique(bl[keep]):
            node = palette[int(local)]
            bname = bone_names.get(node)
            if bname is None:
                log.warn("%s: palette bone %d (node %d) is not in the armature",
                         obj.name, local, node)
                continue
            sel = keep & (bl == local)
            vg = groups.get(bname)
            if vg is None:
                vg = obj.vertex_groups.get(bname) or obj.vertex_groups.new(name=bname)
                groups[bname] = vg
            wq = np.round(ww[sel], 4)
            verts = np.nonzero(sel)[0]
            for uw in np.unique(wq):
                vg.add([int(v) for v in verts[wq == uw]], float(uw), "REPLACE")
                assigned += int((wq == uw).sum())

    log.info("%s: %d vertex groups, %d weight assignments (avg %.2f "
             "influences/vertex)", obj.name, len(groups), assigned,
             float((w > 1e-5).sum(axis=1).mean()))
    return len(groups)


# ---------------------------------------------------------------------------
# animation
# ---------------------------------------------------------------------------

def _sample(times_ms, values, t):
    """Linear / spherical sample of a channel at time t (ms)."""
    n = len(times_ms)
    if n == 0:
        return None
    if t <= times_ms[0]:
        return values[0]
    if t >= times_ms[-1]:
        return values[-1]
    i = int(np.searchsorted(times_ms, t))
    i = max(1, min(i, n - 1))
    t0, t1 = times_ms[i - 1], times_ms[i]
    f = 0.0 if t1 <= t0 else (t - t0) / (t1 - t0)
    a, b = values[i - 1], values[i]
    if len(a) == 4:
        qa = Quaternion((a[3], a[0], a[1], a[2]))
        qb = Quaternion((b[3], b[0], b[1], b[2]))
        q = qa.slerp(qb, f)
        return np.array([q.x, q.y, q.z, q.w], dtype=np.float64)
    return a + (b - a) * f


def import_animations(context, model, arm_obj, bone_names, rest, opts, log):
    if not model.clips:
        log.info("animation: no clips in file")
        return []

    fps = opts["fps"]
    context.scene.render.fps = int(round(fps))
    arm_obj.animation_data_create()

    # rest local matrix per bone, in the SAME space as bone.matrix_local
    xform = opts["xform"]
    mirror = opts["mirror"]
    rest_world = {i: xform @ rest[i] @ mirror for i in rest}
    bone_parent = {}
    for i in bone_names:
        p = model.nodes[i].parent
        while p >= 0 and p not in bone_names:
            p = model.nodes[p].parent
        bone_parent[i] = p if p in bone_names else -1
    rest_local = {}
    for i in bone_names:
        p = bone_parent[i]
        rest_local[i] = (rest_world[p].inverted_safe() @ rest_world[i]
                         if p >= 0 else rest_world[i].copy())

    # The engine's world space is Y up, the mesh is authored Z up. Measured on
    # both reference models: the Pelvis bind position is (~0, ~0, 1.0) while the
    # same bone in node/animation space is (~0, 1.0, ~0). So node -> mesh is a
    # +90 deg rotation about X.
    #
    # This only has to be applied to ROOT bones: for every child the correction
    # appears as G on both sides of  animWorld(parent)^-1 @ animWorld(child)
    # and cancels out.
    align = (Matrix.Rotation(1.5707963267948966, 4, "X")
             if opts["anim_align"] else Matrix.Identity(4))
    root_space = xform @ align
    if opts["anim_align"]:
        log.info("animation: rotating the clip space +90 deg about X so the "
                 "animated character stands upright like the rest pose")

    made = []
    for clip in model.clips:
        if not clip.channels:
            continue
        nframes = max(2, int(round(clip.duration_ms / 1000.0 * fps)) + 1)
        if nframes > opts["max_frames"]:
            log.warn("clip %r: %d frames exceeds the limit (%d), truncated",
                     clip.name, nframes, opts["max_frames"])
            nframes = opts["max_frames"]

        by_node = {}
        for ch in clip.channels:
            by_node.setdefault(ch.node, {})[ch.kind] = ch

        action = bpy.data.actions.new("%s|%s" % (opts["basename"], clip.name))
        action.use_fake_user = True
        arm_obj.animation_data.action = action

        for pb in arm_obj.pose.bones:
            pb.rotation_mode = "QUATERNION"

        # A bone whose own node (and every node between it and its bone
        # parent) has no channel in this clip keeps a CONSTANT local matrix.
        # Those get one static pose instead of nframes x 3 keyframes -- that
        # is the difference between seconds and minutes on a 139 bone rig.
        moving = set()
        for i in bone_names:
            p = bone_parent[i]
            j = i
            guard = 0
            while j >= 0 and j != p and guard < 512:
                if j in by_node:
                    moving.add(i)
                    break
                j = model.nodes[j].parent
                guard += 1
        log.info("clip %-22s %d of %d bones animated", clip.name,
                 len(moving), len(bone_names))

        touched = 0
        for f in range(nframes):
            t = f / fps * 1000.0
            locals_by_node = {}
            for i, n in enumerate(model.nodes):
                chans = by_node.get(i)
                if not chans:
                    continue
                loc = n.translation
                rot = n.rotation
                scl = n.scale if n.has_scale else None
                c = chans.get(CH_LOCATION)
                if c is not None:
                    v = _sample(c.times_ms, c.values, t)
                    if v is not None:
                        loc = tuple(v[:3])
                c = chans.get(CH_ROTATION)
                if c is not None:
                    v = _sample(c.times_ms, c.values, t)
                    if v is not None and len(v) >= 4:
                        rot = tuple(v[:4])
                c = chans.get(CH_SCALE)
                if c is not None:
                    v = _sample(c.times_ms, c.values, t)
                    if v is not None:
                        scl = tuple(v[:3])
                locals_by_node[i] = trs_matrix(loc, rot, scl)

            world = node_world_matrices(model, locals_by_node)
            for i, bname in bone_names.items():
                if f > 0 and i not in moving:
                    continue
                pb = arm_obj.pose.bones.get(bname)
                if pb is None:
                    continue
                p = bone_parent[i]
                # conjugate by the mirror, exactly as the rest pose is
                anim_local = (mirror @ world[p].inverted_safe() @ world[i] @ mirror
                              if p >= 0
                              else root_space @ world[i] @ mirror)
                pb.matrix_basis = rest_local[i].inverted_safe() @ anim_local
                if i in moving:
                    pb.keyframe_insert("location", frame=f + 1)
                    pb.keyframe_insert("rotation_quaternion", frame=f + 1)
                    pb.keyframe_insert("scale", frame=f + 1)
                    touched += 1

        made.append(action)
        nfc = fcurve_count(action)
        log.info("clip %-22s -> action '%s'  %d frames, %d channels, "
                 "%d bone keys, %d F-curves", clip.name, action.name, nframes,
                 len(clip.channels), touched, nfc)
        if touched and not nfc:
            log.error("action %r has NO F-curves although %d keyframes were "
                      "inserted -- the keys did not land in the action",
                      action.name, touched)

    if made:
        _finish_actions(context, arm_obj, made, opts, log,
                        max(2, int(round(model.clips[0].duration_ms / 1000.0 * fps)) + 1))
        if opts["anim_align"]:
            log.info("animation: rest pose is the bind pose, the clips are the "
                     "engine's own poses -- a small difference between the two "
                     "at frame 0 is expected and correct (measured ~5%% of the "
                     "model size on the reference file).")
        else:
            log.warn("animation alignment is OFF: the clips live in the engine's "
                     "Y-up node space while the rest pose is the Z-up bind pose, "
                     "so the character will lie on its back while animating.")
    return made


# ---------------------------------------------------------------------------
# entry point
# ---------------------------------------------------------------------------

def build(context, model, opts, log):
    mat_cache = {}
    objects = []

    arm_obj = None
    bone_names = {}
    rest = {}
    if opts["import_armature"]:
        arm_obj, bone_names, rest, bind, skinned = create_armature(
            context, model, opts, log)

    # Iterate over PLACEMENTS, not over raw groups: a group can be used by
    # several nodes (039_skin8.model instances one weapon twice) and its bone
    # palette is named by the node, not by the group number.
    placed = set()
    for inst in model.instances:
        for sm in model.groups[inst["group"]]:
            mat_name = (model.materials[sm.material]["name"]
                        if sm.material < len(model.materials) else "")
            if opts["skip_billboards"] and mat_name.endswith("_c"):
                log.info("submesh %s skipped: material '%s' ends in '_c' "
                         "(camera-facing billboard cards)", sm.name, mat_name)
                continue
            node = model.nodes[inst["node"]] if inst["node"] < len(model.nodes) else None
            suffix = ""
            if len(model.group_placement(inst["group"])) > 1:
                suffix = "_at_%s" % (node.name if node else inst["node"])
            obj = build_submesh(context, model, sm, opts, log, mat_cache,
                                name_suffix=suffix)
            if obj is None:
                continue
            placed.add(inst["group"])
            objects.append(obj)
            if arm_obj is None or not opts["import_skin"]:
                continue
            if inst["palette"] is not None:
                apply_skinning(obj, model, sm, bone_names, log,
                               palette_index=inst["palette"])
            else:
                # Rigid attachment: no weights in the file, the mesh simply
                # rides on its node. Bind every vertex to that node's bone with
                # weight 1 so the existing armature path carries it.
                bn = bone_names.get(inst["node"])
                if bn is None:
                    p = node.parent if node else -1
                    while p >= 0 and p not in bone_names:
                        p = model.nodes[p].parent
                    bn = bone_names.get(p)
                if bn:
                    vg = obj.vertex_groups.new(name=bn)
                    vg.add(list(range(len(obj.data.vertices))), 1.0, "REPLACE")
                    log.info("%s: rigid, bound to bone '%s'", obj.name, bn)
                else:
                    log.warn("%s: rigid but no bone found for node %d",
                             obj.name, inst["node"])
            obj.parent = arm_obj
            mod = obj.modifiers.new("Armature", "ARMATURE")
            mod.object = arm_obj

    unplaced = [g for g in range(len(model.groups)) if g not in placed]
    if unplaced:
        log.info("%d geometry group(s) are not referenced by any node and were "
                 "skipped: these are particle/effect templates the engine "
                 "spawns at runtime, not placed geometry", len(unplaced))

    if opts["merge_by_distance"] > 0.0 and objects:
        log.warn("merge by distance is enabled (%.6f). The split vertices in "
                 "this format ARE the hard edges -- merging them will smooth "
                 "your hard edges and can break UVs.", opts["merge_by_distance"])
        for obj in objects:
            _merge(context, obj, opts["merge_by_distance"], log)

    actions = []
    if arm_obj is not None and opts["import_animations"]:
        actions = import_animations(context, model, arm_obj, bone_names,
                                    rest, opts, log)

    return objects, arm_obj, actions


def _merge(context, obj, dist, log):
    try:
        context.view_layer.objects.active = obj
        before = len(obj.data.vertices)
        bpy.ops.object.mode_set(mode="EDIT")
        bpy.ops.mesh.select_all(action="SELECT")
        bpy.ops.mesh.remove_doubles(threshold=dist)
        bpy.ops.object.mode_set(mode="OBJECT")
        log.info("%s: merged %d -> %d vertices", obj.name, before,
                 len(obj.data.vertices))
    except Exception as exc:
        log.warn("%s: merge failed: %s", obj.name, exc)
        try:
            bpy.ops.object.mode_set(mode="OBJECT")
        except Exception:
            pass


# ---------------------------------------------------------------------------
# JUMPX (.x) -- older engine, different container, same Blender plumbing
# ---------------------------------------------------------------------------

def _x_rest_matrix(bone, frame):
    # The quaternion is stored CONJUGATED, i.e. it encodes the transposed
    # rotation -- consistent with the rest of this format, whose 4x4 matrices
    # are all row-vector convention with the translation in the last row.
    #
    # This cancels out at the bind frame, so it is invisible in any test that
    # only looks at frame 0, and it barely moves the MEDIAN edge length. It
    # shows up in the MAXIMUM: without the conjugate the worst edge of
    # 020_skin2.x stretches 25.5x during animation and the armour comes apart;
    # with it, 8.6x, the same order as the .model format.
    q = bone.quat[frame]
    m = Quaternion((float(q[3]), -float(q[0]), -float(q[1]),
                    -float(q[2]))).to_matrix().to_4x4()
    if bone.scale is not None:
        sc = bone.scale[frame]
        m = m @ Matrix.Diagonal((float(sc[0]), float(sc[1]),
                                 float(sc[2]), 1.0))
    m.translation = Vector((float(bone.pos[frame][0]),
                            float(bone.pos[frame][1]),
                            float(bone.pos[frame][2])))
    return m


def build_jumpx(context, model, opts, log):
    """Build a parsed JUMPX model.

    Frame 0 of the shared timeline is the bind pose, so the rest matrices and
    the animation live in the SAME space -- unlike the .model format there is
    no node/bind space split and no axis correction is needed.
    """
    xform = opts["xform"]
    mirror = opts["mirror"]

    rest_raw = [_x_rest_matrix(b, 0) for b in model.bones]
    ext = 1.0
    if model.meshes:
        allp = np.concatenate([m.verts for m in model.meshes]).astype(np.float64)
        ext = float(np.linalg.norm(allp.max(axis=0) - allp.min(axis=0)))
    bsize = auto_bone_size(opts, ext, log)

    arm_obj = None
    bone_names = {}
    if opts["import_armature"] and model.bones:
        arm = bpy.data.armatures.new(opts["basename"] + "_Armature")
        arm_obj = bpy.data.objects.new(opts["basename"] + "_Armature", arm)
        context.collection.objects.link(arm_obj)
        context.view_layer.objects.active = arm_obj
        arm_obj.select_set(True)
        bpy.ops.object.mode_set(mode="EDIT")
        try:
            for i, b in enumerate(model.bones):
                nm = b.name or "Bone_%02d" % i
                base, k = nm, 1
                while nm in arm.edit_bones:
                    nm = "%s.%03d" % (base, k)
                    k += 1
                eb = arm.edit_bones.new(nm)
                bone_names[i] = eb.name
                world = xform @ rest_raw[i] @ mirror
                m = world.to_quaternion().to_matrix().to_4x4()
                m.translation = world.translation
                length = bsize
                kids = [c for c in b.children if 0 <= c < len(model.bones)]
                if kids:
                    ds = [((xform @ rest_raw[c] @ mirror).translation
                           - m.translation).length for c in kids]
                    ds = [v for v in ds if v > 1e-5]
                    if ds:
                        length = min(ds)
                eb.head = (0.0, 0.0, 0.0)
                eb.tail = (0.0, max(length, 1e-4), 0.0)
                eb.matrix = m
                eb.length = max(length, 1e-4)
            for i, b in enumerate(model.bones):
                if b.parent in bone_names and i in bone_names:
                    arm.edit_bones[bone_names[i]].parent = \
                        arm.edit_bones[bone_names[b.parent]]
        finally:
            bpy.ops.object.mode_set(mode="OBJECT")
        _tidy_armature(arm_obj, log)
        roots = [b.name for b in model.bones if b.parent < 0]
        log.info("armature '%s': %d bones, %d root(s) %s",
                 arm_obj.name, len(bone_names), len(roots), roots[:6])

    M = np.array(xform.to_3x3())
    T = np.array(xform.translation)
    objects = []
    mat_cache = {}
    for mi, mesh in enumerate(model.meshes):
        name = "%s_%s" % (opts["basename"], mesh.name or "mesh%d" % mi)
        P = mesh.verts.astype(np.float64) @ M.T + T
        faces = mesh.tris[:, ::-1] if opts["flip_faces"] else mesh.tris

        me = bpy.data.meshes.new(name)
        me.from_pydata([tuple(v) for v in P], [],
                       [tuple(int(i) for i in f) for f in faces])
        me.update()

        uvs = mesh.uvs.astype(np.float64).copy()
        if opts["flip_uv_v"]:
            uvs[:, 1] = 1.0 - uvs[:, 1]
        layer = me.uv_layers.new(name="UVMap")
        try:
            lv = np.empty(len(me.loops), dtype=np.int32)
            me.loops.foreach_get("vertex_index", lv)
            layer.data.foreach_set(
                "uv", np.ascontiguousarray(uvs[lv], dtype=np.float32).ravel())
        except Exception as exc:
            log.warn("%s: fast UV path failed (%s)", name, exc)
            for i, loop in enumerate(me.loops):
                layer.data[i].uv = uvs[loop.vertex_index]

        try:
            me.polygons.foreach_set("use_smooth", [True] * len(me.polygons))
        except Exception:
            pass
        # These normals ARE unit vectors straight out of the file, so unlike
        # the .model format they can be used as-is.
        if opts["normals"] != "FLAT":
            n = mesh.normals.astype(np.float64) @ M.T
            ln = np.linalg.norm(n, axis=1, keepdims=True)
            n = n / np.maximum(ln, 1e-9)
            try:
                me.normals_split_custom_set_from_vertices([tuple(v) for v in n])
            except Exception as exc:
                log.warn("%s: custom normals rejected: %s", name, exc)

        if opts["debug_attributes"] and mesh.palette is not None:
            # The bone palette index. Redundant for importing -- the bone
            # indices are in the skin record -- but useful to visualise the
            # draw batches the engine splits the mesh into.
            try:
                ca = me.color_attributes.new(name="JUMPX_palette_index",
                                             type="FLOAT_COLOR", domain="POINT")
                v = mesh.palette.astype(np.float32) / 255.0
                dd = np.ones((len(v), 4), dtype=np.float32)
                dd[:, 0] = dd[:, 1] = dd[:, 2] = v
                ca.data.foreach_set("color", np.ascontiguousarray(dd).ravel())
                log.debug("%s: palette index stored as 'JUMPX_palette_index'", name)
            except Exception as exc:
                log.warn("%s: palette index layer failed: %s", name, exc)

        me.validate(verbose=False, clean_customdata=False)
        me.update()
        obj = bpy.data.objects.new(name, me)
        context.collection.objects.link(obj)

        # Material -> texture comes from the material descriptor, never from
        # the mesh index. On 045.x the two disagree: three meshes share
        # material 1 while the body uses material 0.
        tex = None
        if 0 <= mesh.material < len(model.materials):
            ti = model.materials[mesh.material].get("texture")
            if ti is not None and 0 <= ti < len(model.textures):
                tex = model.textures[ti]
        if tex is None and len(model.textures) == 1:
            tex = model.textures[0]
        mat = mat_cache.get(mesh.material)
        if mat is None:
            mat = bpy.data.materials.new("%s_mat%d" % (opts["basename"], mesh.material))
            mat.use_nodes = True
            bsdf = mat.node_tree.nodes.get("Principled BSDF")
            path = find_texture(tex, opts["texture_dirs"], log) if tex else None
            log.info("material %d texture=%s -> %s", mesh.material, tex,
                     path or "NOT FOUND")
            if path and bsdf:
                try:
                    img = bpy.data.images.load(path, check_existing=True)
                    node = mat.node_tree.nodes.new("ShaderNodeTexImage")
                    node.image = img
                    node.location = (-420, 260)
                    mat.node_tree.links.new(node.outputs["Color"],
                                            bsdf.inputs["Base Color"])
                    mat.node_tree.links.new(node.outputs["Alpha"],
                                            bsdf.inputs["Alpha"])
                except Exception as exc:
                    log.warn("could not load %s: %s", path, exc)
            mat_cache[mesh.material] = mat
        me.materials.append(mat)

        if arm_obj is not None and opts["import_skin"]:
            groups = {}
            assigned = 0
            idx = mesh.bone_idx
            w = mesh.weights.astype(np.float64)
            tot = w.sum(axis=1, keepdims=True)
            w = np.divide(w, np.where(tot > 1e-8, tot, 1.0))
            for slot in range(idx.shape[1]):
                keep = w[:, slot] > 1e-5
                if not keep.any():
                    continue
                for b in np.unique(idx[keep, slot]):
                    bn = bone_names.get(int(b))
                    if bn is None:
                        continue
                    sel = keep & (idx[:, slot] == b)
                    vg = groups.get(bn) or obj.vertex_groups.get(bn) \
                        or obj.vertex_groups.new(name=bn)
                    groups[bn] = vg
                    verts = np.nonzero(sel)[0]
                    wq = np.round(w[sel, slot], 4)
                    for uw in np.unique(wq):
                        vg.add([int(v) for v in verts[wq == uw]], float(uw), "REPLACE")
                        assigned += int((wq == uw).sum())
            obj.parent = arm_obj
            mod = obj.modifiers.new("Armature", "ARMATURE")
            mod.object = arm_obj
            log.info("%s: %d vertex groups, %d weight assignments",
                     name, len(groups), assigned)
        objects.append(obj)
        log.info("%s: %d verts, %d faces", name, len(me.vertices), len(me.polygons))

    actions = []
    if arm_obj is not None and opts["import_animations"] and model.clips:
        actions = _x_animations(context, model, arm_obj, bone_names, rest_raw,
                                opts, log)
    return objects, arm_obj, actions


def _x_animations(context, model, arm_obj, bone_names, rest_raw, opts, log):
    mirror = opts["mirror"]
    arm_obj.animation_data_create()
    context.scene.render.fps = int(round(opts["fps"]))
    for pb in arm_obj.pose.bones:
        pb.rotation_mode = "QUATERNION"

    parent = {i: model.bones[i].parent for i in bone_names}
    rest_local = {}
    for i in bone_names:
        p = parent[i]
        rest_local[i] = (rest_raw[p].inverted_safe() @ rest_raw[i]
                         if p in bone_names else rest_raw[i].copy())

    made = []
    for clip in model.clips:
        first, last = int(clip.start), int(clip.end)
        last = min(last, model.frames - 1)
        n = max(1, last - first + 1)
        if n > opts["max_frames"]:
            log.warn("clip %r: %d frames exceeds the limit, truncated",
                     clip.name, n)
            n = opts["max_frames"]

        action = bpy.data.actions.new("%s|%s" % (opts["basename"], clip.name))
        action.use_fake_user = True
        arm_obj.animation_data.action = action

        # a bone only needs keys if it actually changes inside this range
        moving = set()
        for i in bone_names:
            b = model.bones[i]
            pr = np.asarray(b.pos[first:first + n])
            qr = np.asarray(b.quat[first:first + n])
            if (np.abs(pr - pr[0]).max() > 1e-6
                    or np.abs(qr - qr[0]).max() > 1e-6):
                moving.add(i)

        # Per frame visibility, where the file has it. Exposed as a keyframed
        # custom property rather than by scaling the bone away, so nothing is
        # destroyed and the value can drive whatever the user wants.
        vis_bones = [i for i in bone_names
                     if model.bones[i].visible is not None
                     and not model.bones[i].visible[first:first + n].all()]
        for i in vis_bones:
            pb = arm_obj.pose.bones.get(bone_names[i])
            if pb is not None and "eg3d_visible" not in pb:
                pb["eg3d_visible"] = 1.0

        touched = 0
        for f in range(n):
            src = first + f
            world = {i: _x_rest_matrix(model.bones[i], src) for i in bone_names}
            for i in vis_bones:
                pb = arm_obj.pose.bones.get(bone_names[i])
                if pb is None:
                    continue
                pb["eg3d_visible"] = float(model.bones[i].visible[src])
                pb.keyframe_insert('["eg3d_visible"]', frame=f + 1)
            for i, bn in bone_names.items():
                if f > 0 and i not in moving:
                    continue
                pb = arm_obj.pose.bones.get(bn)
                if pb is None:
                    continue
                p = parent[i]
                anim_local = (world[p].inverted_safe() @ world[i]
                              if p in bone_names else world[i])
                pb.matrix_basis = (mirror
                                   @ rest_local[i].inverted_safe()
                                   @ anim_local @ mirror)
                if i in moving:
                    pb.keyframe_insert("location", frame=f + 1)
                    pb.keyframe_insert("rotation_quaternion", frame=f + 1)
                    pb.keyframe_insert("scale", frame=f + 1)
                    touched += 1
        made.append(action)
        nfc = fcurve_count(action)
        log.info("clip %-26s -> action '%s'  frames %d..%d (%d), %d of %d bones "
                 "animated, %d keys, %d F-curves%s", clip.name, action.name,
                 first, last, n, len(moving), len(bone_names), touched, nfc,
                 "" if not vis_bones else
                 "; %d bone(s) toggle visibility: %s" % (
                     len(vis_bones),
                     ", ".join(model.bones[i].name for i in vis_bones[:4])))
        if touched and not nfc:
            log.error("action %r has NO F-curves although %d keyframes were "
                      "inserted -- the keys did not land in the action",
                      action.name, touched)

    if made:
        _finish_actions(context, arm_obj, made, opts, log,
                        max(2, model.clips[0].end - model.clips[0].start + 1))
    return made
