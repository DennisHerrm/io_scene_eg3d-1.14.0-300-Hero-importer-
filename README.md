<div align="center">

# 🎮 300 Heroes Model Importer

### Advanced EG3D & JUMPX Model Importer for Blender

Import models, skeletons, skin weights, materials and animations from **300 Heroes / 300英雄** directly into Blender.

<br>

[![Blender](https://img.shields.io/badge/Blender-4.2%2B-orange?style=for-the-badge&logo=blender)](https://www.blender.org/)
[![Version](https://img.shields.io/badge/Version-2.9.0-blue?style=for-the-badge)]()
[![License](https://img.shields.io/badge/License-GPL--3.0-green?style=for-the-badge)]()
[![Python](https://img.shields.io/badge/Python-3.x-yellow?style=for-the-badge&logo=python)]()

<br>

**EG3D `.model` • JUMPX `.x` • Skeletons • Skinning • Animations • Diagnostics**

<br>

*Both formats are fully decoded — geometry, normals, skinning and animation.*

</div>

---

## 📖 About

**300 Heroes Model Importer** is a Blender add-on for importing and researching model files from **300 Heroes / 300英雄**.

Every part of both container formats has been reverse engineered and verified against measurable references — not guessed. The importer brings in:

- 🧩 Geometry, including three different vertex layouts
- 🎨 Materials & texture references
- 🦴 Skeletons with correct bind poses
- ⚖️ Skin weights and bone palettes
- 🌈 Vertex colours
- 🎬 Animations, including two compressed variants
- 👁 Per-clip visibility switching
- 🔍 Mesh and animation diagnostics
- 🛠 Reverse-engineering tools

The project doubles as a **research tool for proprietary game model formats** — the repository documents how each field was identified and which hypotheses were ruled out.

---

# ✨ Features

<table>
<tr>
<td width="50%">

### 🧩 Model Import

- EG3D `.model` support
- JUMPX `.x` support, all three layout variants
- Automatic format detection by signature
- Multiple file import
- Multiple submeshes and instancing
- Packed 10:10:10 vertex positions
- Per-buffer addresses from the descriptor

</td>
<td width="50%">

### 🦴 Skeleton & Skinning

- Full armature import
- Bone hierarchy from the name table
- Bind pose from inverse bind matrices
- Scale-carrying bind matrices handled
- Bone palettes
- Vertex weights, up to 4 per vertex
- Armature modifiers

</td>
</tr>

<tr>
<td>

### 🎨 Mesh Data

- UV maps
- Vertex colours
- Material → texture mapping
- Decoded normals (height + azimuth)
- Flat / geometry / file normal modes
- Bone palette index as a colour layer

</td>
<td>

### 🎬 Animation

- All animation clips as Blender Actions
- Uncompressed and **compressed** variants
- Axis-angle rotation decoding
- Optional per-frame scale tracks
- Keys placed at the source key times
- Linear interpolation, no overshoot
- Per-clip visibility keying

</td>
</tr>

<tr>
<td>

### 🔄 Coordinate System

- Automatic handedness detection
- Triangle winding correction
- Mirror X
- Character orientation
- UV flipping (V down → V up)

</td>
<td>

### 🔍 Diagnostics

- Mesh topology and boundary analysis
- Bone axis alignment check
- Skinning rigidity check
- Motion check (catches static decodes)
- Key-collision reporting
- Corrupt-data detection

</td>
</tr>
</table>

---

# 📦 Supported Formats

| Extension | Format | Support |
|---|---|---|
| `.model` | EG3D / ezgame | 🟢 Fully supported |
| `.x` | JUMPX V5.01 | 🟢 Fully supported |

> **Important:** The supported `.x` files are **not standard Microsoft DirectX `.x` files**. They use a proprietary **JUMPX format** and are detected by their internal file signature, not by extension.

### JUMPX layout variants

The `.x` container comes in several shapes. All are detected automatically:

| Variant | Vertex data | Animation |
|---|---|---|
| Standard (25 TOC entries) | `float32` positions and normals | `float32` position + quaternion |
| Older (23 TOC entries) | 10:10:10 packed positions, `int8×3` normals | `float32` |
| Compressed | either | 10:10:10 positions, **axis-angle** rotations, optional scale |

---

# 🖥 Supported Blender Versions

| Blender Version | Status |
|---|---|
| Blender 4.2 | ✅ Supported |
| Blender 4.3 | ✅ Supported |
| Blender 4.4 | ✅ Supported |
| Blender 5.x | ✅ Supported |

> **Minimum required version: Blender 4.2**

---

# 🚀 Installation

## Method 1 — Install from ZIP

> **Important:** **Do not extract the ZIP file before installation.**

1. Download the latest release ZIP.
2. Open Blender.
3. Navigate to:

```text
Edit → Preferences → Get Extensions
```

4. Open the menu in the top-right corner and select:

```text
Install from Disk...
```

5. Select:

```text
io_scene_eg3d-2.9.0.zip
```

6. Blender will install and enable the add-on.

## Method 2 — Classic Add-on Installation

Alternatively:

```text
Edit → Preferences → Add-ons → Install from Disk
```

Select the downloaded ZIP file and enable the add-on.

---

# 📥 Importing Models

After installation, the importer can be found under:

```text
File → Import → 300 Heroes Model (.model, .x)
```

### Multiple File Import

You can select multiple model files at once. The importer processes each of them and detects the format per file.

---

# ⚙️ Import Options

## 🔄 Transform

| Option | Default | Description |
|---|---|---|
| **Scale** | `1.0` | Uniform scale applied on import |
| **Orientation** | `Z up` | How the file's coordinate system is interpreted |
| **Handedness** | `Automatic` | Mirror / winding correction, see below |
| **Character faces** | `-Y` | Which way the character looks after import |
| **Flip UV V** | `on` | The files store V pointing down (DirectX); Blender's V points up |

### Handedness

| Mode | Description |
|---|---|
| Automatic | Decides from signed volume **and** L/R bone positions |
| Mirror X | Force a mirror on the X axis |
| Flip winding only | Reverse triangle winding without mirroring |
| Raw | No correction at all |

**Recommended:** `Automatic`. It measures each file rather than assuming — the three reference characters need three different corrections.

---

# 🦴 Skeleton & Armature

- Bone creation with hierarchy from the file's name table
- Bind poses from the inverse bind matrices
- Automatic bone length (2 % of model size)
- Stick display, so bones don't obscure thin limbs

### Only Skeleton Bones

`on` by default. Imports only bones actually used by the mesh, leaving out attachment, effect and helper bones.

---

# ⚖️ Skin Weights

Vertex groups, bone indices, weights and armature modifiers are created automatically, so models can be posed immediately after import.

---

# 🎬 Animation Support

Animation import is **enabled by default** and no longer experimental.

| Option | Default | Description |
|---|---|---|
| **Animations** | `on` | Import all clips as Actions |
| **Assign first action** | `on` | Apply the first clip right away |
| **Align clips to rest pose** | `on` | Rotates the clip space +90° about X |
| **Rigid props** | `off` | See *Known Limitations* |
| **Ignore zero-scale bones** | `off` | Reveal props the engine hides by scaling |
| **Zero-scale threshold** | `0.01` | What counts as hidden |
| **FPS** | `30` | Key times are rounded ms meant as frames |
| **Max frames / clip** | `600` | Safety limit |

### Why the weapons sometimes disappear

Some models hide props by scaling their bone to almost zero instead of using a
visibility flag. On `336_skin1.model` the two sword bones sit at scale `0.001`
in **all 31 clips**, which collapses the weapon and everything parented under
it. That is why the swords are visible **without** animation and vanish **with**
it — and the 3ds Max importer behaves identically, because the file says so.

Turn on **Ignore zero-scale bones** to force such keys back to `1`.

### Visibility channels

`.model` files can switch whole node subtrees on and off per clip. On
`039_skin8.model` one node carries an entire **second character** — 16 636
vertices — that is only enabled during the `dance` clip. The importer keyframes
`hide_viewport` and `hide_render` accordingly.

---

# 🔺 Geometry Options

## Normals

| Mode | Description |
|---|---|
| **From geometry** ⭐ | Blender calculates them from the mesh |
| **From the file** | Uses the stored normals |
| **Flat** | Flat shading |

For `.model` files the stored normals are a **height + azimuth** encoding, not a
vector — see *Technical Notes*. They decode to within 0.03° of the geometric
normals on flat reference surfaces.

## Merge By Distance

Default `0` (disabled), and that is the recommendation. Game models
intentionally duplicate vertices at UV seams, hard edges and normal splits;
merging them changes the model.

---

# 🎯 Camera Facing Geometry

Materials whose name ends in `_c` may be billboards that the engine rotates
toward the camera. Blender does not reproduce that, so they can look wrong.
Use **Skip '_c' billboards** to leave them out.

---

# 🔍 Diagnostics

The diagnostic system is built for one purpose: **catching a wrong decode
before it reaches the viewport**. Every check has a calibrated threshold, taken
from files that are known good and known broken.

| Check | Healthy | Broken |
|---|---|---|
| Indices in range | 0 out of range | any |
| Winding consistency (interior edges only) | 100 % | < 100 % |
| Bone axis alignment (Biped X axis) | 0.93 – 0.99 | ~0.5 (chance) |
| Skinning rigidity (edges over 3× stretch) | < 0.5 % | ~5 % |
| Motion per frame | ≈ 0.05 | ≈ 0 (static decode) |

### 🕳 Detecting real mesh holes

Apparent holes are usually UV seams or hard edges. The report welds the mesh
and tells the two apart:

| Geometry Issue | Description |
|---|---|
| 🟥 Real Hole | Missing geometry |
| 🟨 Boundary Loop | Open mesh boundary |
| 🟦 UV Seam | Intentional vertex split |
| 🟩 Hard Edge | Normal separation |
| 🟪 Open Shell | Intentional open geometry |

### Why winding is measured on interior edges only

Counting every directed edge punishes open geometry: a perfect two-triangle
card scores 33 % simply because four of its six directed edges are on the
boundary and can never have a partner. Restricting the measure to edges shared
by exactly two faces makes 100 % mean 100 %.

---

# 🛠 Debug & Logging

## Log Levels

| Level | Description |
|---|---|
| ERROR | Only critical errors |
| WARN | Warnings and errors |
| INFO ⭐ | General import information |
| DEBUG | Per-attribute offsets and buffer layouts |
| TRACE | Quantisation constants and bone lists |

## Write Log Next To File

`on` by default. Creates a log next to the imported model:

```text
character.model
character_eg3d_import.log
```

## Write Log Into Blend

Stores the same information inside the `.blend`, reachable from the Scripting
workspace.

## JSON Metadata Dump

Writes the extracted metadata as a Blender Text Block — useful for format
research and for reporting problems.

---

# 🐍 Standalone Parsers

Both parsers run without Blender's `bpy` module:

```bash
python eg3d_parse.py model.model            # EG3D
python eg3d_x.py model.x                    # JUMPX
python eg3d_parse.py model.model --verbose
```

They report container headers, materials, textures, buffer layouts, vertex
attributes, skeleton data and the full diagnostic report.

---

# 🧪 Troubleshooting

## ❌ "File too small" or "does not start with EG3D"

The file itself is truncated, not the importer. One archive contained a
`020_skin3.model` of exactly **1 byte** (the ASCII character `1`) while its 1 MB
texture had extracted fine. Extract the model again.

## 🖼 Texture appears upside down

Toggle **Flip UV V**. The default (`on`) is correct for every file tested.

## 🗡 Weapons or props are missing

Most likely the engine hides them by scaling their bone to `0.001` — see
*Why the weapons sometimes disappear*. Turn on **Ignore zero-scale bones**.

## 🔭 Nothing visible after import

Check the model's size in the log. Scales differ enormously between assets:
`336_skin1.model` is **2.9** units across, `monster_youlong.x` is **508** and
sits between z 30 and 241. Press `Home` in the viewport, or *View → Frame All*.

## 🦴 Bones appear outside the mesh

On thin limbs that is normal. The importer already uses stick display; you can
also hide the armature temporarily.

## 🎞 Animation looks like it stutters

Check the log for key-collision warnings. Two source keys can round to the same
frame at 30 FPS — a median of 4.45 % across the tested files, up to 14.7 % in
the worst. Raising **FPS** to 60 keeps them.

---

# 🧠 Technical Notes

Findings from reverse engineering, each verified against a measurable
reference.

### `.model` normals: height + azimuth

Attribute 1 is not a vector but an angle pair:

```text
int16 c0 -> z    = c0 / 16384        (15 bit, range -1..1)
int16 c1 -> phi  = c1 / 32768 * pi   (16 bit, full circle)
r = sqrt(1 - z*z)
n = (-r*sin(phi), -z, -r*cos(phi))
```

One component needing 15 bits and the other 16 is what ruled out an octahedral
pair. Verified against area-weighted geometric normals: **+0.970 / +0.967 /
+0.973** on curved submeshes and **+1.000** on flat cards, where the reference
is exact.

### `.x` compressed rotations: axis-angle

```text
bits  0..7    uint8   rotation angle IN DEGREES
bits 16..27   int12   axis x, two's complement, negated
bits 32..43   int12   axis y
bits 48..59   int12   axis z

theta = A * pi / 360        (half angle, i.e. A/2 degrees)
q     = (normalise(axis) * sin(theta), cos(theta))
```

Verified against the inverse bind matrices of **569 bones from 13 files**:
median angular error **0.467°**, **99.1 %** below 1°. The remainder is exactly
the 1-degree quantisation of the 8-bit angle.

### The one byte per vertex in `.x`

It is the index into the `bgp` bone palette table, saturating at 255. Checked
on **all 20 514 vertices** of one file: `bgp[byte]` equals the bone list stored
in the same vertex's skin record, **100.0000 %**.

### Bind matrices carry scale — Blender bones cannot

A Blender bone is built from head, tail and roll, so `bone.matrix_local` is
always orthonormal. The bind matrices are not: `039_skin8.model` carries a
uniform scale of **1.6881**. Equating Blender's deform with the correct one
gives a per-bone correction applied **from the right**:

```text
pose_world = anim_world @ rest_raw⁻¹ @ rest_orth
```

Without it the animation sways by up to 13 % of the model size. The 3ds Max
importer of the same project does the same and calls it *Korrektur von RECHTS*.

### Keys go at the source times, and they must be LINEAR

Key times are rounded milliseconds (33, 66, 100) that are meant as frames.
Resampling at `f × 1000/fps` lands between the source keys; holding the last
key turns sparse channels into a staircase. Both are wrong — interpolate on the
frame grid.

Blender also inserts keyframes as **Bezier with auto handles**, which overshoot
wherever the key spacing changes. On one file the spine had 6 rotation keys
against 46 on the leg bones, and the curve left its own value range by **4.5 %**
— every spine key made the foot twitch. All curves are forced to `LINEAR`.

---

# ✅ Regression Testing

The importer is checked against **101 files** — 51 `.x` and 50 `.model` — and
not merely for "it runs":

```text
Regression: 101 files (51 .x, 50 .model)
   Bone axis   median 0.951 (min 0.592)
   Rigidity    median 0.0008 (max 0.0093)
   Animation path: 45 .model (max 0.000000000) and 50 .x (max 0.000000000)
ALL CHECKS PASSED
```

The animation check reproduces Blender's own maths — orthonormal rest,
right-hand correction, frame-grid interpolation, then `pose_world @ rest_orth⁻¹`
— and compares the result vertex by vertex against the reference
`anim_world @ inverse_bind`.

### Two controls every measurement needs

During this work **seven** different metrics rewarded a degenerate solution
with a top score. Two controls catch that:

1. **Identity control.** On one dataset a plain identity rotation scored 7.0 %
   below 1° error, because that many bones genuinely have an identity bind. Any
   hit rate below the control is worthless.
2. **Motion control.** A decode producing near-constant rotations passes every
   rigidity check trivially. Mean change per frame must be in the range of a
   real animation (≈ 0.046).

---

# 📋 Feature Overview

| Feature | Status |
|---|---|
| EG3D `.model` Import | ✅ |
| JUMPX `.x` Import, all variants | ✅ |
| Automatic Format Detection | ✅ |
| Mesh Import | ✅ |
| Multiple Submeshes & Instancing | ✅ |
| UV Maps | ✅ |
| Materials & Texture Mapping | ✅ |
| Decoded Normals | ✅ |
| Skeleton / Armature | ✅ |
| Bone Hierarchy | ✅ |
| Skin Weights | ✅ |
| Vertex Colours | ✅ |
| Animation Import | ✅ |
| Compressed Animation Variants | ✅ |
| Per-Clip Visibility | ✅ |
| Automatic Handedness Detection | ✅ |
| Mesh Diagnostics | ✅ |
| Animation-Path Verification | ✅ |
| Debug Logging | ✅ |
| JSON Metadata Dump | ✅ |
| Standalone Python Parsers | ✅ |
| Rigid Prop Placement | 🚧 Unsolved |

---

# ⚠️ Known Limitations

- **Rigid props** — geometry hanging off a node without bone weights sits in a
  coordinate space that is not understood yet. On `039_skin8.model` the raw
  coordinates and the node world matrix both land far from the body, so the
  option is **off** by default.
- **Key collisions** — at 30 FPS a median of 4.45 % of source keys round onto a
  frame that already has one. Raise **FPS** to keep them.
- Some files contain genuinely corrupt data: all-zero bind matrices, NaN bone
  tracks, clips declaring frames past the end of their own timeline. These are
  detected, repaired where possible, and reported.
- Camera-facing billboard geometry may need manual adjustment.
- Texture availability depends on the extracted game files.

---

# 🤝 Credits

<div align="center">

### Developed by

# DennisH & Black_XeSHTeG

<br>

Special thanks to everyone involved in the research and preservation of the  
**300 Heroes / 300英雄** game file formats.

</div>

---

# 📜 License

This project is licensed under:

**GPL-3.0-or-later**

See the `LICENSE` file for more information.

---

<div align="center">

### ⭐ If you find this project useful, consider giving the repository a star!

<br>

**300 Heroes Model Importer • Blender 4.2+ • v2.9.0**

</div>
