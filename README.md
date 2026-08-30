<div align="center">

# 🎮 300 Heroes Model Importer

### Advanced EG3D & JUMPX Model Importer for Blender

Import models, skeletons, skin weights, materials and animations from **300 Heroes / 300英雄** directly into Blender.

<br>

[![Blender](https://img.shields.io/badge/Blender-4.2%2B-orange?style=for-the-badge&logo=blender)](https://www.blender.org/)
[![Version](https://img.shields.io/badge/Version-1.14.0-blue?style=for-the-badge)]()
[![License](https://img.shields.io/badge/License-GPL--3.0-green?style=for-the-badge)]()
[![Python](https://img.shields.io/badge/Python-3.x-yellow?style=for-the-badge&logo=python)]()

<br>

**EG3D `.model` • JUMPX `.x` • Skeletons • Skinning • Animations • Diagnostics**

</div>

---

## 📖 About

**300 Heroes Model Importer** is a Blender add-on designed for importing and researching model files from **300 Heroes / 300英雄**.

The importer supports multiple proprietary game formats and provides tools for importing:

- 🧩 Geometry
- 🎨 Materials & texture references
- 🦴 Skeletons / Armatures
- ⚖️ Skin weights
- 🌈 Vertex colors
- 🎬 Animations
- 🔍 Advanced mesh diagnostics
- 🛠 Debugging and reverse engineering tools

The project is designed not only as an importer but also as a powerful tool for **researching and analyzing proprietary game model formats**.

---

# ✨ Features

<table>
<tr>
<td width="50%">

### 🧩 Model Import

- EG3D `.model` support
- JUMPX `.x` support
- Automatic format detection
- Multiple file import
- Multiple submeshes
- Vertex & index buffers
- Different vertex layouts

</td>
<td width="50%">

### 🦴 Skeleton & Skinning

- Full armature import
- Bone hierarchy
- Parent / child relationships
- Bind pose support
- Inverse bind matrices
- Bone palettes
- Vertex weights
- Armature modifiers

</td>
</tr>

<tr>
<td>

### 🎨 Mesh Data

- UV maps
- Vertex colors
- Material assignments
- Texture references
- Normal import
- Flat shading
- Automatic normal calculation

</td>
<td>

### 🎬 Animation

- Animation clip import
- Blender Actions
- Adjustable FPS
- Frame limits
- Automatic first action assignment
- Rest pose alignment
- Experimental animation support

</td>
</tr>

<tr>
<td>

### 🔄 Coordinate System

- Automatic handedness detection
- Triangle winding correction
- Mirror X
- Reverse winding
- Character orientation
- UV flipping

</td>
<td>

### 🔍 Diagnostics

- Mesh diagnostics
- Boundary edge analysis
- Non-manifold detection
- UV seam detection
- Hard edge analysis
- Skin weight validation
- Bone palette analysis

</td>
</tr>
</table>

---

# 📦 Supported Formats

| Extension | Format | Support |
|---|---|---|
| `.model` | EG3D / ezgame | 🟢 Supported |
| `.x` | JUMPX V5.01 | 🟢 Supported |

> **Important:** The supported `.x` files are **not standard Microsoft DirectX `.x` files**. They use a proprietary **JUMPX format** and are detected using their internal file signature.

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
io_scene_eg3d-1.14.0.zip
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
File → Import → 300 Heroes EG3D Model
```

Supported file extensions:

```text
.model
.x
```

### Multiple File Import

You can select multiple model files at once. The importer will automatically process each selected file and import them into Blender.

---

# ⚙️ Import Options

## 🔄 Transform

### Scale

Uniformly scales the imported model.

Default:

```text
1.0
```

### Orientation

Controls how the coordinate system of the original model is interpreted. Models are generally imported using a **Z-Up coordinate system**.

### Handedness

| Mode | Description |
|---|---|
| Automatic | Automatically detects the correct orientation |
| Mirror X | Mirrors the model on the X axis |
| Reverse Winding | Reverses triangle winding |
| Raw | Imports without coordinate correction |

**Recommended:** `Automatic`

### Character Facing Direction

Controls which direction the character faces after import.

Default:

```text
-Y
```

### Flip UV V

Flips the V coordinate of the UV map. Enable this option if textures appear upside down.

---

# 🦴 Skeleton & Armature

The importer can reconstruct complete character skeletons.

### Supported Features

- Bone creation
- Bone hierarchy
- Parent / child relationships
- Bind poses
- Inverse bind matrices
- Automatic bone sizing
- Bone palette support

### Only Skeleton Bones

This option imports only bones that are actually used by the mesh.

This helps remove unnecessary:

- Attachment bones
- Effect bones
- Unused helper bones

---

# ⚖️ Skin Weights

Character skinning data can be imported directly into Blender.

Supported data:

- Vertex groups
- Bone indices
- Bone weights
- Armature modifiers
- Skin bindings

Imported models can therefore be animated immediately after import.

---

# 🎨 Materials & Textures

The importer extracts material information from the original model files.

Supported information:

- Material names
- Texture references
- Material groups
- Submesh assignments

> **Note:** Texture extraction and automatic texture assignment may depend on the original game asset structure.

---

# 🌈 Vertex Colors

If available, vertex color information can be imported.

Supported format:

```text
RGBA Vertex Colors
```

---

# 🎬 Animation Support

> **Warning:** Animation support is currently experimental.

The importer supports:

- Animation clips
- Blender Actions
- Adjustable FPS
- Maximum frame limits
- Automatic first Action assignment
- Rest pose alignment

### Default FPS

```text
30 FPS
```

### Default Maximum Frames

```text
600 Frames
```

### Align Clips To Rest Pose

This option attempts to align imported animation clips with the model's rest pose. It is enabled by default and recommended for most models.

---

# 🔺 Geometry Options

## Normals

Three different normal modes are available.

### From Geometry ⭐ Recommended

Blender calculates normals based on the imported geometry.

### From File

Uses the normal data stored inside the original model file.

### Flat

Imports the mesh using flat shading.

## Merge By Distance

Merges vertices that are close to each other.

Default:

```text
0 = Disabled
```

> **Caution:** It is recommended to keep this option disabled.

Game models often intentionally contain duplicated vertices for:

- UV seams
- Hard edges
- Normal splits

Merging these vertices may alter the original model.

---

# 🎯 Camera Facing Geometry

Some materials may contain special camera-facing geometry.

Materials using the suffix:

```text
_c
```

may represent billboards or geometry dynamically rotated towards the camera by the game engine.

Since Blender does not automatically reproduce this behavior, these elements may appear incorrect.

Use:

```text
Skip '_c' Billboards
```

to exclude them during import.

---

# 🔍 Advanced Mesh Diagnostics

One of the major features of this importer is its advanced diagnostic system.

The diagnostic tools can analyze:

- Vertex buffer layouts
- Attribute offsets
- Index buffers
- Mesh topology
- Boundary edges
- Non-manifold geometry
- UV splits
- Hard edge splits
- Triangle winding
- Signed volume
- Edge lengths
- Skin weight sums
- Bone indices
- Bone palettes

## 🕳 Detecting Real Mesh Holes

Game models can sometimes appear to contain holes. However, these apparent holes are often caused by:

- UV seams
- Hard edges
- Split normals
- Separate mesh shells

The diagnostic system helps distinguish between:

| Geometry Issue | Description |
|---|---|
| 🟥 Real Hole | Missing geometry |
| 🟨 Boundary Loop | Open mesh boundary |
| 🟦 UV Seam | Intentional vertex split |
| 🟩 Hard Edge | Normal separation |
| 🟪 Open Shell | Intentional open geometry |

---

# 📊 Boundary Loop Analysis

The importer can generate reports for boundary edges and loops.

This helps identify whether open geometry is intentional.

Possible intentional open geometry:

- Capes
- Ribbons
- Clothing
- Alpha cards
- Hair cards
- Open mesh shells

> **Note:** Not every boundary edge represents a broken model.

---

# 🛠 Debug & Logging

The importer includes several debugging tools.

## Log Levels

```text
ERROR
WARN
INFO
DEBUG
TRACE
```

| Level | Description |
|---|---|
| ERROR | Only critical errors |
| WARN | Warnings and errors |
| INFO | General import information |
| DEBUG | Detailed import information |
| TRACE | Very detailed internal data |

**Recommended for normal use:** `INFO`

## Write Log Next To File

Automatically creates a log file next to the imported model.

Example:

```text
character.model
character_eg3d_import.log
```

## Write Log Into Blend

Stores import information directly inside the `.blend` file.

The logs can later be accessed through Blender's:

```text
Scripting Workspace
```

## JSON Metadata Dump

Extracted metadata can be stored as a Blender Text Block.

This is especially useful for:

- Reverse engineering
- File format research
- Debugging
- Unknown model analysis

---

# 🐍 Standalone Parser

The project also includes a standalone parser that can be used without Blender.

```text
eg3d_parse.py
```

The parser does not require Blender's `bpy` module.

This makes it possible to analyze model files directly using Python.

### Basic Usage

```bash
python eg3d_parse.py model.model
```

### Verbose Output

```bash
python eg3d_parse.py model.model --verbose
```

The parser can provide information about:

- Container headers
- Materials
- Textures
- Buffer layouts
- Vertex attributes
- Mesh diagnostics
- Skeleton data

---

# 🧪 Troubleshooting

## ❌ Model appears mirrored

Try changing the **Handedness** option.

Recommended:

```text
Automatic
```

If necessary, try:

```text
Mirror X
```

or:

```text
Reverse Winding
```

## 🖼 Texture appears upside down

Enable:

```text
Flip UV V
```

## 🕳 Model appears to have holes

Enable:

```text
Mesh Diagnostics
```

Then inspect the generated report.

Many apparent holes are caused by UV seams or intentionally split vertices.

## 🦴 Bones appear outside the mesh

Blender may display bones using octahedral shapes.

On thin parts of a character, such as arms or legs, bones can appear to extend outside the mesh.

This does **not** necessarily indicate broken geometry.

You can change the armature display mode or hide the armature temporarily.

---

# 🧠 Technical Overview

The importer is designed to handle proprietary game model structures and provides automatic detection and correction for common issues.

```text
Game Model File
       │
       ▼
┌─────────────────┐
│ Format Detection │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│ Buffer Parsing  │
└────────┬────────┘
         │
         ├──────────────► Materials
         ├──────────────► Geometry
         ├──────────────► UV Maps
         ├──────────────► Vertex Colors
         ├──────────────► Skeleton
         ├──────────────► Skinning
         └──────────────► Animations
                          │
                          ▼
                  ┌───────────────┐
                  │ Blender Scene │
                  └───────────────┘
```

---

# 📋 Feature Overview

| Feature | Status |
|---|---|
| EG3D `.model` Import | ✅ |
| JUMPX `.x` Import | ✅ |
| Automatic Format Detection | ✅ |
| Mesh Import | ✅ |
| Multiple Submeshes | ✅ |
| UV Maps | ✅ |
| Materials | ✅ |
| Texture References | ✅ |
| Skeleton / Armature | ✅ |
| Bone Hierarchy | ✅ |
| Skin Weights | ✅ |
| Vertex Groups | ✅ |
| Vertex Colors | ✅ |
| Animation Import | 🧪 Experimental |
| Multiple File Import | ✅ |
| Automatic Handedness Detection | ✅ |
| Orientation Options | ✅ |
| Normal Import | ✅ |
| Mesh Diagnostics | ✅ |
| Boundary Loop Analysis | ✅ |
| Debug Logging | ✅ |
| JSON Metadata Dump | ✅ |
| Standalone Python Parser | ✅ |

---

# ⚠️ Known Limitations

- Animation import is currently experimental.
- Different game assets may use different coordinate spaces.
- Camera-facing billboard geometry may require manual adjustments.
- Texture availability depends on the original extracted game files.
- Some unknown or unusual model variants may require further research.

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

**300 Heroes Model Importer • Blender 4.2+**

</div>
