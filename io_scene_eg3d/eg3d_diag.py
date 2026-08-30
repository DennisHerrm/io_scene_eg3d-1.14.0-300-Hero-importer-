# SPDX-License-Identifier: GPL-3.0-or-later
"""
Diagnostics for decoded EG3D models.

This is the part you want when somebody says "there are holes everywhere".
It answers, with numbers, which of these is actually true:

  1. the buffers are being read at the wrong offset       -> layout gaps, out of
                                                             range indices,
                                                             |quat| != 1
  2. the triangle list is misinterpreted                  -> non-manifold edges,
                                                             degenerate faces,
                                                             huge edges
  3. the mesh is simply split at UV/hard-edge seams       -> many raw boundary
     (normal for game assets, NOT a hole)                    edges but almost
                                                             none after welding
  4. the mesh really is an open shell (capes, ribbons,    -> boundary loops
     alpha cards)                                            survive welding and
                                                             are large/flat
  5. the winding is inward (left-handed source)           -> negative signed
                                                             volume

All of it is printed; nothing is silently "fixed".
"""

import numpy as np

try:  # works both as a Blender extension module and as a standalone script
    from .eg3d_parse import (ATTR_POSITION, ATTR_UV, ATTR_WEIGHTS, ATTR_BONES)
except (ImportError, ValueError):  # pragma: no cover
    from eg3d_parse import (ATTR_POSITION, ATTR_UV, ATTR_WEIGHTS, ATTR_BONES)


def _edges(tris):
    e = np.concatenate([tris[:, [0, 1]], tris[:, [1, 2]], tris[:, [2, 0]]])
    return np.sort(e, axis=1)


def winding_consistency(tw):
    """Share of INTERIOR edges whose two faces agree on direction.

    Counting every directed edge instead punishes open geometry: a perfect
    two-triangle card scores 33.3% simply because four of its six directed
    edges are on the boundary and can never have a partner. Restricting the
    measure to edges shared by exactly two faces makes 100% mean 100%.
    Returns (percent, interior edge count).
    """
    e = _edges(tw)
    ue, ec = np.unique(e, axis=0, return_counts=True)
    interior = ue[ec == 2]
    if len(interior) == 0:
        return None, 0
    de = np.concatenate([tw[:, [0, 1]], tw[:, [1, 2]], tw[:, [2, 0]]])
    k = de[:, 0].astype(np.int64) * (1 << 32) + de[:, 1]
    ks = np.sort(k)
    # an interior edge is consistent when exactly one of its two directions
    # occurs once each, i.e. a->b and b->a are both present
    a = interior[:, 0].astype(np.int64) * (1 << 32) + interior[:, 1]
    b = interior[:, 1].astype(np.int64) * (1 << 32) + interior[:, 0]
    ia = np.clip(np.searchsorted(ks, a), 0, len(ks) - 1)
    ib = np.clip(np.searchsorted(ks, b), 0, len(ks) - 1)
    ok = (ks[ia] == a) & (ks[ib] == b)
    return float(100.0 * ok.mean()), int(len(interior))


def weld_map(pos, precision=5):
    key = np.round(pos.astype(np.float64), precision)
    _, inv = np.unique(key, axis=0, return_inverse=True)
    return inv.astype(np.int64)


def analyse_submesh(sm, model_diag, weld_precision=5):
    """Return a dict of measurements for one submesh."""
    pos = sm.attrs.get(ATTR_POSITION)
    tris = sm.triangles
    out = {"name": sm.name, "verts": sm.vertex_count,
           "tris": 0 if tris is None else len(tris)}

    if pos is None or tris is None or len(tris) == 0:
        return out

    finite = np.isfinite(pos).all()
    out["positions_finite"] = bool(finite)
    mn = np.nanmin(pos, axis=0)
    mx = np.nanmax(pos, axis=0)
    out["bbox_min"] = [float(v) for v in mn]
    out["bbox_max"] = [float(v) for v in mx]

    out["index_min"] = int(tris.min())
    out["index_max"] = int(tris.max())
    out["indices_out_of_range"] = int((tris >= sm.vertex_count).sum())

    used = np.unique(tris)
    out["unused_verts"] = int(sm.vertex_count - len(used))

    deg = ((tris[:, 0] == tris[:, 1]) | (tris[:, 1] == tris[:, 2]) |
           (tris[:, 0] == tris[:, 2]))
    out["degenerate_tris"] = int(deg.sum())

    # duplicated faces (same 3 vertices)
    fs = np.sort(tris, axis=1)
    _, cnt = np.unique(fs, axis=0, return_counts=True)
    out["duplicate_faces"] = int((cnt > 1).sum())

    # raw topology
    e = _edges(tris)
    ue, ec = np.unique(e, axis=0, return_counts=True)
    out["edges_raw"] = int(len(ue))
    out["boundary_raw"] = int((ec == 1).sum())
    out["manifold_raw"] = int((ec == 2).sum())
    out["nonmanifold_raw"] = int((ec > 2).sum())

    # topology after welding coincident vertices
    inv = weld_map(pos, weld_precision)
    tw = inv[tris]
    ew = _edges(tw)
    uew, ecw = np.unique(ew, axis=0, return_counts=True)
    out["welded_verts"] = int(inv.max() + 1)
    out["edges_welded"] = int(len(uew))
    out["boundary_welded"] = int((ecw == 1).sum())
    out["nonmanifold_welded"] = int((ecw > 2).sum())

    # winding consistency: a directed edge should appear with its reverse
    pct, ninner = winding_consistency(tw)
    out["winding_consistent_pct"] = pct
    out["interior_edges"] = ninner

    # edge lengths relative to the WHOLE model diagonal (never per submesh!)
    L = np.linalg.norm(pos[ue[:, 0]] - pos[ue[:, 1]], axis=1)
    L = L[np.isfinite(L)]
    if len(L):
        out["edge_p50"] = float(np.percentile(L, 50))
        out["edge_p99"] = float(np.percentile(L, 99))
        out["edge_max"] = float(L.max())
        out["edges_over_10pct_diag"] = int((L > 0.10 * model_diag).sum())
        out["edges_over_20pct_diag"] = int((L > 0.20 * model_diag).sum())

    # signed volume -> winding direction (only meaningful for closed shells)
    pw = np.zeros((int(inv.max()) + 1, 3), dtype=np.float64)
    pw[inv] = pos
    v = np.einsum("ij,ij->i", pw[tw[:, 0]],
                  np.cross(pw[tw[:, 1]], pw[tw[:, 2]])) / 6.0
    out["signed_volume"] = float(v.sum())

    uv = sm.attrs.get(ATTR_UV)
    if uv is not None and np.isfinite(uv).all():
        out["uv_min"] = [float(v) for v in uv.min(axis=0)]
        out["uv_max"] = [float(v) for v in uv.max(axis=0)]

    w = sm.attrs.get(ATTR_WEIGHTS)
    if w is not None:
        s = w.sum(axis=1)
        out["weightsum_min"] = float(np.nanmin(s))
        out["weightsum_med"] = float(np.nanmedian(s))
        out["weightsum_max"] = float(np.nanmax(s))
        out["verts_bad_weightsum"] = int((np.abs(s - 1.0) > 0.02).sum())
        out["avg_influences"] = float((w > 1e-5).sum(axis=1).mean())

    b = sm.attrs.get(ATTR_BONES)
    if b is not None:
        out["bone_index_max"] = int(b.max())

    return out


def boundary_loops(pos, tris, weld_precision=5, max_loops=4000):
    """Return welded boundary loops as lists of welded vertex indices."""
    inv = weld_map(pos, weld_precision)
    tw = inv[tris]
    e = _edges(tw)
    ue, ec = np.unique(e, axis=0, return_counts=True)
    bnd = ue[ec == 1]
    if len(bnd) == 0:
        return [], inv
    adj = {}
    for a, b in bnd:
        adj.setdefault(int(a), []).append(int(b))
        adj.setdefault(int(b), []).append(int(a))
    seen = set()
    loops = []
    for start in adj:
        if start in seen or len(loops) >= max_loops:
            continue
        loop = []
        cur = start
        prev = None
        while cur is not None and cur not in seen:
            seen.add(cur)
            loop.append(cur)
            nxt = None
            for c in adj.get(cur, ()):
                if c != prev and c not in seen:
                    nxt = c
                    break
            prev, cur = cur, nxt
        if len(loop) >= 3:
            loops.append(loop)
    return loops, inv


def report(model, log=None, weld_precision=5):
    """Print the whole diagnosis. Returns the list of per-submesh dicts."""
    allpos = []
    for _, sm in model.all_submeshes():
        p = sm.attrs.get(ATTR_POSITION)
        if p is not None and np.isfinite(p).all():
            allpos.append(p)
    if allpos:
        cat = np.concatenate(allpos)
        gmin, gmax = cat.min(axis=0), cat.max(axis=0)
        diag = float(np.linalg.norm(gmax - gmin))
    else:
        gmin = gmax = np.zeros(3)
        diag = 1.0

    if log:
        log.info("=" * 74)
        log.info("MESH DIAGNOSTICS")
        log.info("=" * 74)
        log.info("model bbox  min=%s", np.round(gmin, 4).tolist())
        log.info("            max=%s", np.round(gmax, 4).tolist())
        log.info("            size=%s  diagonal=%.4f",
                 np.round(gmax - gmin, 4).tolist(), diag)
        log.info("NOTE: always measure 'giant triangle' thresholds against THIS "
                 "diagonal, never against a per-submesh diagonal.")

    results = []
    for _, sm in model.all_submeshes():
        r = analyse_submesh(sm, diag, weld_precision)
        results.append(r)
        if not log:
            continue
        mat = model.materials[sm.material]["name"] if sm.material < len(model.materials) else "?"
        log.info("-" * 74)
        log.info("submesh %s   material[%d]=%s", r["name"], sm.material, mat)
        log.info("  vertices %d   triangles %d   unused verts %d",
                 r["verts"], r["tris"], r.get("unused_verts", 0))
        if r.get("indices_out_of_range"):
            log.error("  %d INDICES OUT OF RANGE -> wrong buffer base or wrong "
                      "index stride", r["indices_out_of_range"])
        log.info("  degenerate %d   duplicate faces %d",
                 r.get("degenerate_tris", 0), r.get("duplicate_faces", 0))
        log.info("  raw topology     : edges %d  boundary %d  non-manifold %d",
                 r.get("edges_raw", 0), r.get("boundary_raw", 0),
                 r.get("nonmanifold_raw", 0))
        log.info("  welded topology  : verts %d  boundary %d  non-manifold %d",
                 r.get("welded_verts", 0), r.get("boundary_welded", 0),
                 r.get("nonmanifold_welded", 0))
        br, bw = r.get("boundary_raw", 0), r.get("boundary_welded", 0)
        if br and bw < br * 0.15:
            log.info("  -> %d of %d 'boundary' edges disappear after welding: "
                     "those are UV/hard-edge splits, NOT holes.", br - bw, br)
        if r.get("winding_consistent_pct") is None:
            log.info("  winding consistent: n/a (no interior edges, the mesh is "
                     "all single cards)")
        else:
            log.info("  winding consistent: %.1f%% of %d interior edges",
                     r["winding_consistent_pct"], r.get("interior_edges", 0))
        log.info("  signed volume     : %+.5f  (%s)", r.get("signed_volume", 0.0),
                 "faces point OUTWARD" if r.get("signed_volume", 0) > 0
                 else "faces point INWARD -> left-handed source, flip winding")
        if "edge_max" in r:
            log.info("  edge length       : p50=%.4f p99=%.4f max=%.4f  "
                     "(>10%% diag: %d, >20%% diag: %d)",
                     r["edge_p50"], r["edge_p99"], r["edge_max"],
                     r["edges_over_10pct_diag"], r["edges_over_20pct_diag"])
            if r["edges_over_20pct_diag"]:
                log.warn("  -> %d edges longer than 20%% of the model diagonal. "
                         "Those are the classic 'bridge triangles'.",
                         r["edges_over_20pct_diag"])
        if "uv_min" in r:
            log.info("  UV range          : %s .. %s",
                     np.round(r["uv_min"], 4).tolist(),
                     np.round(r["uv_max"], 4).tolist())
        if "weightsum_med" in r:
            log.info("  weight sums       : min=%.4f med=%.4f max=%.4f  "
                     "bad=%d  avg influences=%.2f",
                     r["weightsum_min"], r["weightsum_med"], r["weightsum_max"],
                     r["verts_bad_weightsum"], r["avg_influences"])
        if "bone_index_max" in r:
            pal = model.palettes[sm.group] if sm.group < len(model.palettes) else None
            psz = len(pal["bones"]) if pal else -1
            ok = "OK" if (psz < 0 or r["bone_index_max"] < psz) else "OUT OF RANGE"
            log.info("  bone indices      : max=%d, palette size=%d  [%s]",
                     r["bone_index_max"], psz, ok)

    if log:
        log.info("=" * 74)
    return results


def hole_report(model, log=None, weld_precision=5, compact_frac=0.03,
                max_report=25):
    """List welded boundary loops, sorted by size, with a compactness measure.

    A loop whose bounding box is a large fraction of the model is not a hole,
    it is the open border of a shell (cape hem, ribbon edge, alpha card).
    Filling those with a centre fan creates giant sheets across the model.
    """
    allpos = [sm.attrs[ATTR_POSITION] for _, sm in model.all_submeshes()
              if ATTR_POSITION in sm.attrs]
    if not allpos:
        return []
    cat = np.concatenate(allpos)
    diag = float(np.linalg.norm(cat.max(axis=0) - cat.min(axis=0))) or 1.0

    out = []
    for _, sm in model.all_submeshes():
        pos = sm.attrs.get(ATTR_POSITION)
        if pos is None or sm.triangles is None or not len(sm.triangles):
            continue
        loops, inv = boundary_loops(pos, sm.triangles, weld_precision)
        pw = np.zeros((int(inv.max()) + 1, 3), dtype=np.float64)
        pw[inv] = pos
        recs = []
        for lp in loops:
            p = pw[np.asarray(lp, dtype=np.int64)]
            ext = float(np.linalg.norm(p.max(axis=0) - p.min(axis=0))) / diag
            recs.append({"submesh": sm.name, "verts": len(lp), "extent": ext,
                         "centre": p.mean(axis=0).tolist(),
                         "compact": ext < compact_frac})
        recs.sort(key=lambda r: -r["verts"])
        out.extend(recs)
        if log:
            comp = sum(1 for r in recs if r["compact"])
            log.info("submesh %s: %d boundary loops (%d compact / %d open borders)",
                     sm.name, len(recs), comp, len(recs) - comp)
            for r in recs[:max_report]:
                log.info("   loop %4d verts  extent %5.1f%% of diag  centre %s  %s",
                         r["verts"], r["extent"] * 100.0,
                         np.round(r["centre"], 3).tolist(),
                         "COMPACT (real hole candidate)" if r["compact"]
                         else "open border (do NOT fan-fill)")
    return out


# ---------------------------------------------------------------------------
# handedness detection
# ---------------------------------------------------------------------------

def signed_volume(verts, tris):
    """Sum of tetrahedron volumes. Negative means faces point inwards."""
    p = np.asarray(verts, dtype=np.float64)
    t = np.asarray(tris, dtype=np.int64)
    if len(t) == 0:
        return 0.0
    return float(np.einsum("ij,ij->i", p[t[:, 0]],
                           np.cross(p[t[:, 1]], p[t[:, 2]])).sum() / 6.0)


def detect_handedness(bone_positions, volume, log=None):
    """Decide what a left-handed source file needs to read correctly.

    Two independent measurements:

      * the SIGN OF THE VOLUME says whether exactly one orientation flip is
        needed at all (negative = faces currently point inwards)
      * the L/R BONE POSITIONS say whether that flip has to be a mirror.
        A character facing -Y (Blender's front) must have its bones named
        "... L ..." on the +X side. If they sit at -X the geometry itself is
        mirrored and only negating X puts left and right back where their
        names say.

    The two are independent: a file can need a winding flip without being
    mirrored, which is exactly how the two 300 Heroes formats differ.
    Returns (mirror_x, flip_faces).
    """
    pairs = []
    for name, pos in bone_positions.items():
        if " L " in name:
            r = name.replace(" L ", " R ", 1)
            if r in bone_positions:
                pairs.append((float(pos[0]), float(bone_positions[r][0])))
    mirrored = None
    if pairs:
        left = sum(a for a, _ in pairs) / len(pairs)
        right = sum(b for _, b in pairs) / len(pairs)
        if abs(left - right) > 1e-4:
            mirrored = left < right
        if log:
            log.info("handedness: %d L/R bone pairs, mean X left %+.3f right %+.3f",
                     len(pairs), left, right)
    elif log:
        log.warn("handedness: no L/R bone pairs found, cannot tell whether the "
                 "geometry is mirrored")

    if mirrored is None:
        mirrored = False
    need_flip = volume < 0.0
    flip_faces = need_flip != mirrored
    if log:
        log.info("handedness: signed volume %+.1f -> %s", volume,
                 "one orientation flip needed" if need_flip else "already outward")
        log.info("handedness: AUTO decided mirror_x=%s, flip_winding=%s%s",
                 mirrored, flip_faces,
                 "  (bones named L sit on the -X side, so the geometry is "
                 "mirrored)" if mirrored else "")
    return mirrored, flip_faces


def report_x(model, log=None, weld_precision=4):
    """Same topology diagnosis for a parsed JUMPX model."""
    if not model.meshes:
        return []
    allp = np.concatenate([m.verts for m in model.meshes]).astype(np.float64)
    gmin, gmax = allp.min(axis=0), allp.max(axis=0)
    diag = float(np.linalg.norm(gmax - gmin)) or 1.0
    if log:
        log.info("=" * 74)
        log.info("MESH DIAGNOSTICS (JUMPX)")
        log.info("=" * 74)
        log.info("model bbox  min=%s", np.round(gmin, 3).tolist())
        log.info("            max=%s  diagonal=%.3f", np.round(gmax, 3).tolist(), diag)

    out = []
    for i, mesh in enumerate(model.meshes):
        P = mesh.verts.astype(np.float64)
        T = mesh.tris.astype(np.int64)
        vc = len(P)
        r = {"name": mesh.name, "verts": vc, "tris": len(T)}
        deg = int(((T[:, 0] == T[:, 1]) | (T[:, 1] == T[:, 2]) |
                   (T[:, 0] == T[:, 2])).sum())
        _, fc = np.unique(np.sort(T, axis=1), axis=0, return_counts=True)
        e = _edges(T)
        ue, ec = np.unique(e, axis=0, return_counts=True)
        inv = weld_map(P, weld_precision)
        tw = inv[T]
        uew, ecw = np.unique(_edges(tw), axis=0, return_counts=True)
        pct, ninner = winding_consistency(tw)
        L = np.linalg.norm(P[ue[:, 0]] - P[ue[:, 1]], axis=1)
        nrm = np.linalg.norm(mesh.normals.astype(np.float64), axis=1)
        ws = mesh.weights.astype(np.float64).sum(axis=1)
        r.update({
            "degenerate": deg, "duplicate_faces": int((fc > 1).sum()),
            "boundary_raw": int((ec == 1).sum()),
            "nonmanifold_raw": int((ec > 2).sum()),
            "welded_verts": int(inv.max() + 1),
            "boundary_welded": int((ecw == 1).sum()),
            "nonmanifold_welded": int((ecw > 2).sum()),
            "winding_consistent_pct": pct, "interior_edges": ninner,
            "signed_volume": signed_volume(P, T),
            "edges_over_20pct_diag": int((L > 0.2 * diag).sum()),
        })
        out.append(r)
        if not log:
            continue
        log.info("-" * 74)
        log.info("mesh %d '%s': %d verts, %d tris, material %d",
                 i, mesh.name, vc, len(T), mesh.material)
        log.info("  degenerate %d   duplicate faces %d   unused verts %d",
                 deg, r["duplicate_faces"], vc - len(np.unique(T)))
        log.info("  raw topology     : edges %d  boundary %d  non-manifold %d",
                 len(ue), r["boundary_raw"], r["nonmanifold_raw"])
        log.info("  welded topology  : verts %d  boundary %d  non-manifold %d",
                 r["welded_verts"], r["boundary_welded"], r["nonmanifold_welded"])
        if r["boundary_raw"] and r["boundary_welded"] < r["boundary_raw"] * 0.4:
            log.info("  -> %d of %d 'boundary' edges disappear after welding: "
                     "UV/hard-edge splits, NOT holes.",
                     r["boundary_raw"] - r["boundary_welded"], r["boundary_raw"])
        if r["boundary_welded"]:
            log.info("  -> %d boundary edges survive welding. On plate armour "
                     "and capes that is the real, intended shape, not a decode "
                     "error.", r["boundary_welded"])
        if r["winding_consistent_pct"] is None:
            log.info("  winding consistent: n/a (no interior edges, the mesh is "
                     "all single cards)")
        else:
            log.info("  winding consistent: %.1f%% of %d interior edges",
                     r["winding_consistent_pct"], r["interior_edges"])
        log.info("  signed volume     : %+.1f", r["signed_volume"])
        log.info("  edge length       : p50=%.3f p99=%.3f max=%.3f  (>20%% diag: %d)",
                 np.percentile(L, 50), np.percentile(L, 99), L.max(),
                 r["edges_over_20pct_diag"])
        log.info("  normals |n|       : min %.5f max %.5f", nrm.min(), nrm.max())
        log.info("  weight sums       : min %.5f max %.5f", ws.min(), ws.max())
    if log:
        log.info("=" * 74)
    return out


# ---------------------------------------------------------------------------
# validators that catch a wrong rotation convention
# ---------------------------------------------------------------------------

def safe_bind_world(bind_rows):
    """Inverse of a stored inverse-bind matrix, or None when it is singular.

    263_skin5.model contains a bind matrix that cannot be inverted. Letting
    numpy raise there killed the whole validation step.
    """
    M = np.asarray(bind_rows, dtype=np.float64).T
    if not np.isfinite(M).all() or abs(np.linalg.det(M)) < 1e-12:
        return None
    return np.linalg.inv(M)


def bone_axis_alignment(world_by_index, children_by_index, log=None, label=""):
    """Do the bone axes point at their children?

    Both formats rig with a 3ds Max Biped, whose bones point along their LOCAL
    X axis. With the correct rotation convention one axis dominates hard
    (measured: .x 0.955, .model 0.978). With a wrong one -- a transposed or
    conjugated quaternion, say -- all three sit near 0.5, i.e. random.

    This is completely independent of the mesh, so it catches a rotation bug
    that the bind pose hides.
    """
    acc = [0.0, 0.0, 0.0]
    n = 0
    for i, W in world_by_index.items():
        kids = [c for c in children_by_index.get(i, ()) if c in world_by_index]
        if not kids:
            continue
        Wm = np.asarray(W)
        if not np.isfinite(Wm).all():
            continue
        d = np.asarray(world_by_index[kids[0]])[:3, 3] - Wm[:3, 3]
        ln = float(np.linalg.norm(d))
        if ln < 1e-6:
            continue
        d = d / ln
        n += 1
        for ax in range(3):
            # Bind matrices can carry scale, so the columns are not unit
            # vectors. Without normalising, the "dot product" can exceed 1.0 --
            # 039_skin8.model reported X = 1.309.
            axis = Wm[:3, ax]
            al = float(np.linalg.norm(axis))
            if al < 1e-9:
                continue
            acc[ax] += abs(float(np.dot(axis / al, d)))
    if not n:
        return None
    res = [v / n for v in acc]
    if log:
        log.info("%sbone axis alignment: X %.3f  Y %.3f  Z %.3f  (%d bones)",
                 label, res[0], res[1], res[2], n)
        # Calibration: character rigs land at 0.93-0.99 with the right
        # convention and near 0.5 with a wrong one. Effect and prop rigs have
        # no Biped at all and legitimately sit lower, so only a value close to
        # chance is treated as an error.
        if max(res) < 0.6:
            log.error("%sno bone axis points at its children (best %.3f, "
                      "chance is ~0.5) -- the rotation convention is probably "
                      "wrong", label, max(res))
        elif max(res) < 0.85:
            log.warn("%sbone axes align only loosely with the hierarchy "
                     "(best %.3f). Normal for effect rigs without a Biped, "
                     "suspicious for a character", label, max(res))
    return res


def model_animation_rigidity(model, log=None, samples=5):
    """Rigidity check for .model files, mirroring the JUMPX one.

    Reports the MAXIMUM edge stretch, never the median: a median of 1.000 is
    perfectly compatible with a model that visibly tears apart.
    """
    from .eg3d_parse import (ATTR_POSITION, ATTR_BONES, ATTR_WEIGHTS,
                             CH_LOCATION, CH_ROTATION, CH_SCALE)
    subs = model.all_submeshes()
    if not subs or not model.clips:
        if log and not model.clips:
            log.info("animation rigidity: file has no clips, nothing to check")
        return None
    _, sm = max(subs, key=lambda x: x[1].vertex_count)
    # The bone palette is named by the placing node, not by the group number.
    pal_idx = sm.group
    for inst in getattr(model, "instances", ()):
        if inst["group"] == sm.group and inst["palette"] is not None:
            pal_idx = inst["palette"]
            break
    P = sm.attrs.get(ATTR_POSITION)
    if P is None or sm.triangles is None:
        return None
    P = P.astype(np.float64)
    h = np.concatenate([P, np.ones((len(P), 1))], axis=1)
    T = sm.triangles.astype(np.int64)
    E = np.unique(np.sort(np.concatenate(
        [T[:, [0, 1]], T[:, [1, 2]], T[:, [2, 0]]]), axis=1), axis=0)
    L0 = np.linalg.norm(P[E[:, 0]] - P[E[:, 1]], axis=1)
    bi = sm.attrs[ATTR_BONES].astype(np.int64)
    bw = sm.attrs[ATTR_WEIGHTS].astype(np.float64)
    bw = bw / np.maximum(bw.sum(axis=1, keepdims=True), 1e-9)
    if pal_idx >= len(model.palettes):
        if log:
            log.info("animation rigidity: largest submesh has no bone palette, "
                     "skipped")
        return None
    pal = model.palettes[pal_idx]["bones"]
    # The stored 64 byte matrix IS the inverse bind, in row-vector convention.
    # Transposing gives the column-vector form -- do NOT invert on top of that.
    IB = {}
    singular = 0
    for p in model.palettes:
        for li, b in enumerate(p["bones"]):
            if b in IB:
                continue
            M = np.asarray(p["bind"][li], dtype=np.float64).T
            if not np.isfinite(M).all() or abs(np.linalg.det(M)) < 1e-12:
                singular += 1
                continue
            IB[b] = M
    if singular and log:
        log.warn("%d bind matrix/matrices are singular or non-finite and were "
                 "skipped for the rigidity check", singular)

    def q2m(q):
        x, y, z, w = [float(v) for v in q]
        s = 2.0 / max(x * x + y * y + z * z + w * w, 1e-12)
        return np.array(
            [[1 - s * (y * y + z * z), s * (x * y - z * w), s * (x * z + y * w)],
             [s * (x * y + z * w), 1 - s * (x * x + z * z), s * (y * z - x * w)],
             [s * (x * z - y * w), s * (y * z + x * w), 1 - s * (x * x + y * y)]])

    def sample(ch, t):
        tm, v = ch.times_ms, ch.values
        if len(tm) == 0:
            return None
        if t <= tm[0]:
            return v[0]
        if t >= tm[-1]:
            return v[-1]
        i = max(1, min(int(np.searchsorted(tm, t)), len(tm) - 1))
        t0, t1 = tm[i - 1], tm[i]
        f = 0.0 if t1 <= t0 else (t - t0) / (t1 - t0)
        a, b = v[i - 1].astype(np.float64), v[i].astype(np.float64)
        if len(a) == 4 and np.dot(a, b) < 0:
            b = -b
        return a + (b - a) * f

    worst, worst_frac, worst_at = 0.0, 0.0, (None, 0.0)
    for clip in model.clips:
        by = {}
        for ch in clip.channels:
            by.setdefault(ch.node, {})[ch.kind] = ch
        for j in range(samples):
            t = clip.duration_ms * j / max(samples - 1, 1)
            loc = {}
            for i, n in enumerate(model.nodes):
                tt = np.array(n.translation, dtype=np.float64)
                q = np.array(n.rotation, dtype=np.float64)
                sc = np.array(n.scale, dtype=np.float64) if n.has_scale else None
                c = by.get(i)
                if c:
                    if CH_LOCATION in c:
                        r = sample(c[CH_LOCATION], t)
                        if r is not None:
                            tt = np.array(r[:3], dtype=np.float64)
                    if CH_ROTATION in c:
                        r = sample(c[CH_ROTATION], t)
                        if r is not None:
                            q = np.array(r[:4], dtype=np.float64)
                            q = q / max(float(np.linalg.norm(q)), 1e-12)
                    if CH_SCALE in c:
                        r = sample(c[CH_SCALE], t)
                        if r is not None:
                            sc = np.array(r[:3], dtype=np.float64)
                M = np.eye(4)
                R = q2m(q)
                if sc is not None:
                    R = R @ np.diag(sc)
                M[:3, :3] = R
                M[:3, 3] = tt
                loc[i] = M
            Wd = {}

            def world(i):
                if i in Wd:
                    return Wd[i]
                M = loc[i]
                p = model.nodes[i].parent
                if p >= 0:
                    M = world(p) @ M
                Wd[i] = M
                return M

            for i in range(len(model.nodes)):
                world(i)
            v = np.zeros((len(P), 3))
            for s in range(4):
                w = bw[:, s]
                for li in np.unique(bi[:, s]):
                    node = pal[int(li)]
                    if node not in IB:
                        continue
                    Mx = Wd[node] @ IB[node]
                    sel = (bi[:, s] == li) & (w > 1e-6)
                    if sel.any():
                        v[sel] += (h[sel] @ Mx.T)[:, :3] * w[sel, None]
            L = np.linalg.norm(v[E[:, 0]] - v[E[:, 1]], axis=1)
            ratio = L / np.maximum(L0, 1e-9)
            # Divide by the frame's own median: a clip is allowed to scale the
            # whole character uniformly. 234_skin10_huicheng.model puts a
            # factor of 21.35 on its root node, which made every single edge
            # look "stretched" although nothing tears.
            med = float(np.median(ratio))
            if med > 1e-6:
                ratio = ratio / med
            worst_frac = max(worst_frac, float((ratio > 3.0).mean()))
            r = float(np.max(ratio))
            if r > worst:
                worst, worst_at = r, (clip.name, t)
    if log:
        log.info("animation rigidity: worst edge stretch %.2fx (clip %r at %.0f ms), "
                 "worst frame has %.2f%% of edges over 3x",
                 worst, worst_at[0], worst_at[1], 100.0 * worst_frac)
        from .eg3d_x import _rigidity_verdict
        _rigidity_verdict(worst_frac, log)
    return worst, worst_frac
