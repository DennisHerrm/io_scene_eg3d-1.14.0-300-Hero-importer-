# SPDX-License-Identifier: GPL-3.0-or-later
"""
300 Heroes / EG3D (.model) importer for Blender 4.2 and newer.

File > Import > 300 Heroes EG3D Model (.model)
"""

# Blender 4.2+ strips bl_info from the module namespace when the package is
# loaded as an EXTENSION (blender_manifest.toml present). Reading bl_info at
# runtime therefore raises NameError -- keep the version in a plain constant.
ADDON_VERSION = (1, 14, 0)

bl_info = {
    "name": "300 Heroes Model (.model / .x)",
    "author": "reverse engineered from 157_skin11.model / 334.model",
    "version": ADDON_VERSION,
    "blender": (4, 2, 0),
    "location": "File > Import > 300 Heroes Model (.model, .x)",
    "description": "Import EG3D / ezgame .model files (mesh, UV, skeleton, "
                   "skin weights, optional animation) with verbose diagnostics",
    "category": "Import-Export",
}

import importlib
import os
import sys
import traceback

import bpy
from bpy.props import (BoolProperty, CollectionProperty, EnumProperty,
                       FloatProperty, IntProperty, StringProperty)
from bpy.types import Operator, Panel
from bpy_extras.io_utils import ImportHelper
from mathutils import Matrix

from . import eg3d_log, eg3d_parse, eg3d_diag, eg3d_build, eg3d_x

for _m in (eg3d_log, eg3d_parse, eg3d_diag, eg3d_build, eg3d_x):
    importlib.reload(_m)


AXIS_ITEMS = (
    ("Z_UP", "Z up (as stored)", "Use the file's coordinates unchanged. "
                                 "These models are already Z-up."),
    ("Y_UP", "Y up -> Z up", "Rotate +90 deg around X (use if your model "
                             "lies on its face)"),
)

HAND_ITEMS = (
    ("AUTO", "Automatic (recommended)",
     "Measure it per file: the sign of the mesh volume says whether one "
     "orientation flip is needed, the L/R bone positions say whether that "
     "flip has to be a mirror. The two 300 Heroes formats differ here, so a "
     "fixed setting is wrong for one of them"),
    ("MIRROR_X", "Mirror X",
     "Negate X on the mesh, the skeleton and the animation. Measured on both "
     "reference models: the character's toes point -Y (Blender's front) but "
     "the bones named 'Bip001 L ...' sit at -X, i.e. on the character's right. "
     "Negating X puts them back where their names say and makes faces point "
     "outwards at the same time"),
    ("FLIP_WINDING", "Flip winding only",
     "Keep the stored coordinates and reverse the triangle order. Faces point "
     "outwards, but the model stays a mirror image of the original - left and "
     "right are swapped relative to the bone names"),
    ("NONE", "Raw (no correction)",
     "Import the data exactly as stored. Faces will point inwards"),
)

FACE_ITEMS = (
    ("-Y", "-Y (Blender standard)", "Front View shows the face"),
    ("X", "+X", "Rotate 90 deg about Z"),
    ("Y", "+Y", "Rotate 180 deg about Z"),
    ("-X", "-X", "Rotate -90 deg about Z"),
)

NORMAL_ITEMS = (
    ("GEOMETRY", "From geometry (recommended)",
     "Let Blender compute normals. The format splits vertices at hard edges, "
     "so smooth shading reproduces the original hard/soft edges by itself."),
    ("FILE", "From the file",
     "Use the normals stored in the model. In .model files attribute 1 turned "
     "out to be a height plus azimuth encoding, verified at dot +0.97 against "
     "geometric normals and +1.000 on flat card meshes. .x files store plain "
     "unit vectors and always use them."),
    ("FLAT", "Flat", "Flat shading"),
)

LOG_ITEMS = (
    ("ERROR", "Errors only", ""),
    ("WARN", "Warnings", ""),
    ("INFO", "Info (recommended)", ""),
    ("DEBUG", "Debug", "Adds per-attribute offsets and buffer layout details"),
    ("TRACE", "Trace (everything)", "Adds quantisation constants and bone lists"),
)


class EG3D_OT_import(Operator, ImportHelper):
    """Import a 300 Heroes model: EG3D (.model) or JUMPX (.x)"""
    bl_idname = "import_scene.eg3d_model"
    bl_label = "Import 300 Heroes Model"
    bl_options = {"UNDO", "PRESET"}

    filename_ext = ".model"
    filter_glob: StringProperty(default="*.model;*.x", options={"HIDDEN"})
    files: CollectionProperty(type=bpy.types.OperatorFileListElement,
                              options={"HIDDEN", "SKIP_SAVE"})
    directory: StringProperty(subtype="DIR_PATH", options={"HIDDEN", "SKIP_SAVE"})

    # ---- transform -------------------------------------------------------
    global_scale: FloatProperty(
        name="Scale", default=1.0, min=0.0001, max=10000.0,
        description="Uniform scale applied on import")
    axis_mode: EnumProperty(name="Orientation", items=AXIS_ITEMS, default="Z_UP")
    handedness: EnumProperty(
        name="Handedness", items=HAND_ITEMS, default="AUTO",
        description="The file declares leftHandCoord=true, so it needs one "
                    "orientation flip to read correctly in Blender")
    face_axis: EnumProperty(
        name="Character faces", items=FACE_ITEMS, default="-Y",
        description="Which world axis the character should look along after "
                    "import. Blender's own convention is -Y, so that Front "
                    "View (Numpad 1) shows the face. Other values just add a "
                    "rotation about Z")
    flip_uv_v: BoolProperty(
        name="Flip UV V", default=False,
        description="Verified against the real texture of 020_skin2.x: the UVs "
                    "need NO flip, the atlas lines up pixel for pixel as "
                    "stored. Only turn this on if a texture comes out upside "
                    "down")

    # ---- what to import --------------------------------------------------
    import_armature: BoolProperty(name="Armature", default=True)
    import_skin: BoolProperty(name="Skin weights", default=True)
    only_skinned_bones: BoolProperty(
        name="Only skeleton bones", default=True,
        description="Import only bones referenced by a bone palette plus "
                    "their ancestors. Turning this off also imports effect "
                    "attachment points, which use a different axis "
                    "convention and stick out of the model")
    import_colors: BoolProperty(name="Vertex colours", default=True)
    import_animations: BoolProperty(
        name="Animations (experimental)", default=False,
        description="Import all clips as actions. Slow, and the animated pose "
                    "space differs from the bind pose space (see the log)")
    anim_align: BoolProperty(
        name="Align clips to rest pose", default=True,
        description="The engine animates in a Y-up world while the mesh is "
                    "authored Z-up. This rotates the clip space +90 deg about "
                    "X so the animated character stands upright like the rest "
                    "pose. Turn off to get the raw engine orientation")
    assign_action: BoolProperty(
        name="Assign first action", default=False,
        description="Leave the armature in its bind pose after import and let "
                    "you pick a clip yourself in the Action Editor. All clips "
                    "are imported either way and kept with a fake user")
    fps: FloatProperty(name="FPS", default=30.0, min=1.0, max=240.0)
    max_frames: IntProperty(name="Max frames / clip", default=600, min=2,
                            max=20000)

    # ---- geometry handling ----------------------------------------------
    normals_mode: EnumProperty(name="Normals", items=NORMAL_ITEMS,
                               default="GEOMETRY")
    skip_billboards: BoolProperty(
        name="Skip '_c' billboards", default=False,
        description="Materials ending in '_c' are camera-facing card sets. "
                    "Their geometry is a template the engine rotates every "
                    "frame, so it looks arbitrary in a static viewer")
    merge_by_distance: FloatProperty(
        name="Merge by distance", default=0.0, min=0.0, max=1.0, precision=6,
        description="0 = off (recommended). The duplicated vertices in this "
                    "format ARE the hard edges; merging them destroys that")
    bone_size: FloatProperty(
        name="Default bone length", default=0.0, min=0.0, max=1000.0,
        description="Length for bones that have no child. 0 = automatic, "
                    "2%% of the model size. A fixed value is wrong for one of "
                    "the two formats, whose scales differ by a factor of 40")

    # ---- debugging -------------------------------------------------------
    log_level: EnumProperty(name="Log level", items=LOG_ITEMS, default="INFO")
    run_diagnostics: BoolProperty(
        name="Mesh diagnostics", default=True,
        description="Topology / winding / weight report: tells you whether "
                    "'holes' are real holes, UV splits, or a decode bug")
    run_hole_report: BoolProperty(
        name="Boundary loop report", default=False,
        description="List every boundary loop with its size, so you can tell "
                    "real holes from open shell borders (cape hems, ribbons)")
    debug_attributes: BoolProperty(
        name="Keep undecoded attributes", default=False,
        description="Store extra per-vertex data as colour layers: attribute 1 "
                    "of .model files (meaning still unknown) and the bone "
                    "palette index of .x files")
    write_log_file: BoolProperty(
        name="Write .log next to file", default=True)
    write_text_block: BoolProperty(
        name="Write log into .blend", default=True,
        description="Creates a Text data block you can read in the Scripting "
                    "workspace")
    dump_json: BoolProperty(
        name="Dump JSON metadata", default=False,
        description="Store the raw metadata of the file as a Text data block")

    def draw(self, context):
        pass  # panels below

    def execute(self, context):
        # Changing an option in the file browser sidebar can drop the file
        # selection, which leaves filepath pointing at the FOLDER. Catch that
        # here instead of letting open() fail with a bare Errno 2.
        paths = []
        if self.files and self.directory:
            for f in self.files:
                if f.name:
                    paths.append(os.path.join(self.directory, f.name))
        if self.filepath:
            paths.append(self.filepath)

        seen = set()
        files = []
        for p in paths:
            if p and p not in seen and os.path.isfile(p):
                seen.add(p)
                files.append(p)
        if not files:
            shown = self.filepath or self.directory or "(nothing)"
            self.report({"ERROR"},
                        "No file selected. %r is a folder, not a model file. "
                        "Pick a .model or .x file in the browser, then press "
                        "Import." % shown)
            return {"CANCELLED"}
        paths = files

        ok = 0
        for p in paths:
            try:
                self._import_one(context, p)
                ok += 1
            except Exception as exc:
                tb = traceback.format_exc()
                print(tb)
                # put the traceback where the user can actually find it
                try:
                    name = os.path.splitext(os.path.basename(p))[0] + "_eg3d_error.txt"
                    txt = bpy.data.texts.get(name) or bpy.data.texts.new(name)
                    txt.clear()
                    txt.write(tb)
                except Exception:
                    pass
                last = [l for l in tb.strip().splitlines() if l.strip().startswith("File ")]
                where = last[-1].strip() if last else "?"
                self.report({"ERROR"}, "%s: %s (%s)"
                            % (os.path.basename(p), exc, where))
        if ok == 0:
            return {"CANCELLED"}
        return {"FINISHED"}

    # ------------------------------------------------------------------
    def _validators(self, model, is_x, log):
        """Checks that catch a wrong rotation convention.

        Both are here because a conjugated quaternion once slipped through:
        it cancels out at the bind pose and barely moves the MEDIAN edge
        length, so only a maximum and a mesh-independent check see it.
        """
        try:
            import numpy as _np
            if is_x:
                worlds, kids = {}, {}
                for i, b in enumerate(model.bones):
                    q = b.quat[0]
                    x, y, z, w = (-float(q[0]), -float(q[1]),
                                  -float(q[2]), float(q[3]))
                    sc = 2.0 / max(x * x + y * y + z * z + w * w, 1e-12)
                    M = _np.eye(4)
                    M[:3, :3] = [
                        [1 - sc * (y * y + z * z), sc * (x * y - z * w), sc * (x * z + y * w)],
                        [sc * (x * y + z * w), 1 - sc * (x * x + z * z), sc * (y * z - x * w)],
                        [sc * (x * z - y * w), sc * (y * z + x * w), 1 - sc * (x * x + y * y)]]
                    M[:3, 3] = b.pos[0]
                    worlds[i] = M
                    kids[i] = b.children
                eg3d_diag.bone_axis_alignment(worlds, kids, log=log)
                if self.import_animations:
                    eg3d_x.animation_rigidity(model, log=log)
            else:
                worlds, kids = {}, {}
                singular = 0
                for p in model.palettes:
                    for li, b in enumerate(p["bones"]):
                        if b in worlds or b >= len(model.nodes):
                            continue
                        W = eg3d_diag.safe_bind_world(p["bind"][li])
                        if W is None:
                            singular += 1
                            continue
                        worlds[b] = W
                if singular:
                    log.warn("%d bind matrix/matrices are singular and were "
                             "skipped by the validators", singular)
                for i, n in enumerate(model.nodes):
                    kids[i] = n.children
                eg3d_diag.bone_axis_alignment(worlds, kids, log=log)
                if self.import_animations:
                    eg3d_diag.model_animation_rigidity(model, log=log)
        except Exception as exc:
            log.warn("validators failed: %s", exc)

    def _handedness(self, model, is_x, log):
        """Return (mirror_x, flip_faces) for the chosen mode."""
        if self.handedness == "MIRROR_X":
            return True, False
        if self.handedness == "FLIP_WINDING":
            return False, True
        if self.handedness == "NONE":
            return False, False
        # AUTO -- measure it
        try:
            import numpy as _np
            bones = {}
            verts = tris = None
            if is_x:
                for b in model.bones:
                    bones[b.name] = tuple(float(v) for v in b.pos[0])
                big = max(model.meshes, key=lambda m: len(m.verts))
                verts, tris = big.verts, big.tris
            else:
                seen = set()
                for pal in model.palettes:
                    for li, bi in enumerate(pal["bones"]):
                        if bi in seen or bi >= len(model.nodes):
                            continue
                        seen.add(bi)
                        m = Matrix(pal["bind"][li]).transposed().inverted_safe()
                        bones[model.nodes[bi].name] = tuple(m.translation)
                big = max((sm for _, sm in model.all_submeshes()),
                          key=lambda s: s.vertex_count)
                verts = big.attrs.get(eg3d_parse.ATTR_POSITION)
                tris = big.triangles
            vol = eg3d_diag.signed_volume(verts, tris)
            return eg3d_diag.detect_handedness(bones, vol, log)
        except Exception as exc:
            log.warn("handedness detection failed (%s), falling back to "
                     "Mirror X", exc)
            return True, False

    def _import_one(self, context, path):
        base = os.path.splitext(os.path.basename(path))[0]
        log = eg3d_log.Logger(
            level=self.log_level,
            to_file=(eg3d_log.default_log_path(path)
                     if self.write_log_file else None),
            prefix="EG3D")

        log.rule("EG3D import: %s" % os.path.basename(path))
        log.info("Blender %s, addon %s",
                 ".".join(str(v) for v in bpy.app.version),
                 ".".join(str(v) for v in ADDON_VERSION))
        log.info("file: %s", path)
        log.info("buffer base = %d (offsets in the JSON are relative to the "
                 "binary block, which starts at byte 12)",
                 eg3d_parse.BLOCK_BASE)

        is_x = eg3d_x.is_jumpx(path)
        log.info("format: %s", "JUMPX (.x, older engine)" if is_x
                 else "EG3D (.model, newer engine)")
        model = eg3d_x.parse_jumpx(path, log=log) if is_x \
            else eg3d_parse.parse_model(path, log=log)

        if self.run_diagnostics:
            if is_x:
                eg3d_diag.report_x(model, log=log)
                self._validators(model, True, log)
            else:
                eg3d_diag.report(model, log=log)
                self._validators(model, False, log)
        if self.run_hole_report and not is_x:
            log.rule("boundary loops")
            eg3d_diag.hole_report(model, log=log)

        if self.dump_json and not is_x:
            import json
            name = base + "_eg3d_meta.json"
            txt = bpy.data.texts.get(name) or bpy.data.texts.new(name)
            txt.clear()
            txt.write(json.dumps(model.meta, indent=1)[:20_000_000])
            log.info("metadata written to text block '%s'", name)

        xform = Matrix.Scale(self.global_scale, 4)
        if self.axis_mode == "Y_UP":
            xform = Matrix.Rotation(1.5707963267948966, 4, "X") @ xform
        # The mirror has to reach the skeleton and the animation too, not just
        # the mesh, so it is folded into the import transform and additionally
        # handed over on its own for conjugating bone matrices.
        turn = {"-Y": 0.0, "X": 1.5707963267948966,
                "Y": 3.141592653589793, "-X": -1.5707963267948966}[self.face_axis]
        if turn:
            xform = Matrix.Rotation(turn, 4, "Z") @ xform
            log.info("facing: rotating %+.0f deg about Z so the character "
                     "looks along %s", turn * 57.29577951308232, self.face_axis)

        do_mirror, flip_faces = self._handedness(model, is_x, log)
        mirror = Matrix.Identity(4)
        if do_mirror:
            mirror = Matrix.Diagonal((-1.0, 1.0, 1.0, 1.0))
            xform = xform @ mirror
        log.info("handedness: %s -> mirror_x=%s flip_winding=%s "
                 "(mesh transform det=%+.3f)", self.handedness, do_mirror,
                 flip_faces, xform.determinant())

        d = os.path.dirname(path)
        opts = {
            "basename": base,
            "xform": xform,
            "mirror": mirror,
            "flip_faces": flip_faces,
            "flip_uv_v": self.flip_uv_v,
            "import_armature": self.import_armature,
            "import_skin": self.import_skin and self.import_armature,
            "only_skinned_bones": self.only_skinned_bones,
            "import_colors": self.import_colors,
            "import_animations": self.import_animations,
            "anim_align": self.anim_align,
            "assign_action": self.assign_action,
            "fps": self.fps,
            "max_frames": self.max_frames,
            "normals": self.normals_mode,
            "skip_billboards": self.skip_billboards,
            "merge_by_distance": self.merge_by_distance,
            "bone_size": self.bone_size,
            "debug_attributes": self.debug_attributes,
            "texture_dirs": [d, os.path.join(d, "textures"),
                             os.path.join(d, "texture"), os.path.join(d, "tex"),
                             os.path.dirname(d),
                             os.path.join(os.path.dirname(d), "textures")],
        }
        log.rule("building Blender data")
        if is_x:
            objects, arm, actions = eg3d_build.build_jumpx(context, model, opts, log)
        else:
            objects, arm, actions = eg3d_build.build(context, model, opts, log)

        log.rule("done")
        log.info("%d object(s), armature=%s, %d action(s)",
                 len(objects), arm.name if arm else "-", len(actions))
        log.info(log.summary())
        if log.file_path:
            log.info("log file: %s", log.file_path)
        log.close(text_name=(base + "_eg3d_import.log")
                  if self.write_text_block else None)

        self.report({"WARNING" if log.counts.get("ERROR") else "INFO"},
                    "EG3D: %s (%s)" % (base, log.summary()))


# ---------------------------------------------------------------------------
# file browser side panels
# ---------------------------------------------------------------------------

class _EG3DPanel(Panel):
    bl_space_type = "FILE_BROWSER"
    bl_region_type = "TOOL_PROPS"
    bl_parent_id = "FILE_PT_operator"
    bl_options = {"DEFAULT_CLOSED"}

    @classmethod
    def poll(cls, context):
        op = context.space_data.active_operator
        return op and op.bl_idname == "IMPORT_SCENE_OT_eg3d_model"


class EG3D_PT_transform(_EG3DPanel):
    bl_label = "Transform"
    bl_options = set()

    def draw(self, context):
        op = context.space_data.active_operator
        lay = self.layout
        lay.use_property_split = True
        lay.prop(op, "global_scale")
        lay.prop(op, "axis_mode")
        lay.prop(op, "handedness")
        lay.prop(op, "face_axis")
        lay.prop(op, "flip_uv_v")


class EG3D_PT_include(_EG3DPanel):
    bl_label = "Include"
    bl_options = set()

    def draw(self, context):
        op = context.space_data.active_operator
        lay = self.layout
        lay.use_property_split = True
        lay.prop(op, "import_armature")
        row = lay.row()
        row.enabled = op.import_armature
        row.prop(op, "import_skin")
        row = lay.row()
        row.enabled = op.import_armature
        row.prop(op, "only_skinned_bones")
        lay.prop(op, "import_colors")
        lay.prop(op, "import_animations")
        col = lay.column()
        col.enabled = op.import_animations
        col.prop(op, "assign_action")
        col.prop(op, "anim_align")
        col.prop(op, "fps")
        col.prop(op, "max_frames")


class EG3D_PT_geometry(_EG3DPanel):
    bl_label = "Geometry"

    def draw(self, context):
        op = context.space_data.active_operator
        lay = self.layout
        lay.use_property_split = True
        lay.prop(op, "normals_mode")
        lay.prop(op, "skip_billboards")
        lay.prop(op, "merge_by_distance")
        lay.prop(op, "bone_size")


class EG3D_PT_debug(_EG3DPanel):
    bl_label = "Debug"

    def draw(self, context):
        op = context.space_data.active_operator
        lay = self.layout
        lay.use_property_split = True
        lay.prop(op, "log_level")
        lay.prop(op, "run_diagnostics")
        lay.prop(op, "run_hole_report")
        lay.prop(op, "debug_attributes")
        lay.prop(op, "write_log_file")
        lay.prop(op, "write_text_block")
        lay.prop(op, "dump_json")


def menu_func_import(self, context):
    self.layout.operator(EG3D_OT_import.bl_idname,
                         text="300 Heroes Model (.model, .x)")


CLASSES = (EG3D_OT_import, EG3D_PT_transform, EG3D_PT_include,
           EG3D_PT_geometry, EG3D_PT_debug)


def register():
    for c in CLASSES:
        bpy.utils.register_class(c)
    bpy.types.TOPBAR_MT_file_import.append(menu_func_import)


def unregister():
    bpy.types.TOPBAR_MT_file_import.remove(menu_func_import)
    for c in reversed(CLASSES):
        bpy.utils.unregister_class(c)


if __name__ == "__main__":
    register()
