"""Convert a Silent Hill 1 area (all IPD cells + global PLM) into a TrenchBroom
map: Quake3 (Valve) .map + PNG material collection + provenance manifest.

Usage:
  python ipd2map.py --area DRU [--disc <extracted disc>] [--gamedir <out>]
                    [--flip-winding]
Paths default to sh1paths.json / auto-detection (see setup_paths.py).

Coordinate convention (docs/DESIGN.md): TB = (SH.x, SH.z, -SH.y) / 4, i.e.
1 TB unit = 4 Q8 units; cell = 2560 TB, subcell = 512 TB, 1 SH unit = 64 TB.

Every SH tri/quad becomes a thin prism brush whose visible face carries the
exact PSX texel UVs via Valve220 axes; other prism faces get special/skip.
surfaceValue = face ID into the manifest; surfaceFlags bit0=isTransparent,
bit1=second half of a split quad, bit2=model lives in the global PLM.
"""

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from sh1fmt import Ipd, Lm, Tim

SCALE = 4.0          # Q8 units per TB unit
CELL_Q8 = 10240
THICKNESS = 8.0      # prism depth in TB units (= 32 Q8 = 0.125 SH unit)
# Merged quads must be EXACTLY planar/affine (tolerances = fp noise only):
# a brush face is a perfect plane, so any real deviation would deform geometry,
# and UV deviation >= 0.5 texel would break byte-exact map2ipd round-trips.
EPS_PLANAR = 1e-3    # TB units; quad planarity tolerance
EPS_UV = 0.45        # texels; quad affine-UV tolerance
SKIP_MAT = "special/skip"
UNTEX_MAT = "special/untextured"

FLAG_TRANSPARENT = 1
FLAG_SECOND_HALF = 2
FLAG_GLOBAL_PLM = 4


# ---------- small vector helpers (avoid a numpy dependency) ----------

def v_sub(a, b):
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])

def v_add(a, b):
    return (a[0] + b[0], a[1] + b[1], a[2] + b[2])

def v_scale(a, s):
    return (a[0] * s, a[1] * s, a[2] * s)

def v_cross(a, b):
    return (a[1] * b[2] - a[2] * b[1],
            a[2] * b[0] - a[0] * b[2],
            a[0] * b[1] - a[1] * b[0])

def v_dot(a, b):
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]

def v_len(a):
    return (a[0] * a[0] + a[1] * a[1] + a[2] * a[2]) ** 0.5

def solve3(m, rhs):
    """Solve 3x3 m . x = rhs (m given as rows); None if singular.

    Inverse columns of a row matrix (r0,r1,r2) are (r1xr2, r2xr0, r0xr1)/det,
    so x = (b0*(r1xr2) + b1*(r2xr0) + b2*(r0xr1)) / det.
    """
    det = v_dot(m[0], v_cross(m[1], m[2]))
    if abs(det) < 1e-12:
        return None
    c0 = v_cross(m[1], m[2])
    c1 = v_cross(m[2], m[0])
    c2 = v_cross(m[0], m[1])
    return tuple(
        (rhs[0] * c0[i] + rhs[1] * c1[i] + rhs[2] * c2[i]) / det for i in range(3))


def fnum(x):
    """Format a float the way TB tolerates: minimal but precise."""
    if x == int(x):
        return str(int(x))
    return repr(x)


# ---------- geometry ----------

def to_tb(q8):
    """SH Q8 world coords -> TB coords."""
    return (q8[0] / SCALE, q8[2] / SCALE, -q8[1] / SCALE)


def transform_vertex(v, rot, trans, cell_off):
    """Model-local s16 Q8 -> SH world Q8 (float)."""
    x = (rot[0][0] * v[0] + rot[0][1] * v[1] + rot[0][2] * v[2]) / 4096.0 + trans[0] + cell_off[0]
    y = (rot[1][0] * v[0] + rot[1][1] * v[1] + rot[1][2] * v[2]) / 4096.0 + trans[1]
    z = (rot[2][0] * v[0] + rot[2][1] * v[1] + rot[2][2] * v[2]) / 4096.0 + trans[2] + cell_off[1]
    return (x, y, z)


def poly_normal(pts):
    """Newell normal of a polygon (unnormalized)."""
    n = [0.0, 0.0, 0.0]
    for i, p in enumerate(pts):
        q = pts[(i + 1) % len(pts)]
        n[0] += (p[1] - q[1]) * (p[2] + q[2])
        n[1] += (p[2] - q[2]) * (p[0] + q[0])
        n[2] += (p[0] - q[0]) * (p[1] + q[1])
    return tuple(n)


def solve_uv_axes(pts, uvs, normal):
    """Valve220 axes: A with dot(p,A)+off = u for all pts (A in the face plane).
    Returns (uAxis, uOff, vAxis, vOff) or None if degenerate."""
    e1, e2 = v_sub(pts[1], pts[0]), v_sub(pts[2], pts[0])
    m = (e1, e2, normal)
    ua = solve3(m, (uvs[1][0] - uvs[0][0], uvs[2][0] - uvs[0][0], 0.0))
    va = solve3(m, (uvs[1][1] - uvs[0][1], uvs[2][1] - uvs[0][1], 0.0))
    if ua is None or va is None:
        return None
    return ua, uvs[0][0] - v_dot(pts[0], ua), va, uvs[0][1] - v_dot(pts[0], va)


def face_line(p1, p2, p3, material, axes, flags=0, value=0):
    pts = " ".join(f"( {fnum(p[0])} {fnum(p[1])} {fnum(p[2])} )" for p in (p1, p2, p3))
    if axes:
        ua, uo, va, vo = axes
        uv = (f"[ {fnum(ua[0])} {fnum(ua[1])} {fnum(ua[2])} {fnum(uo)} ] "
              f"[ {fnum(va[0])} {fnum(va[1])} {fnum(va[2])} {fnum(vo)} ]")
    else:
        uv = "[ 1 0 0 0 ] [ 0 -1 0 0 ]"
    return f"{pts} {material} {uv} 0 1 1 0 {flags} {fnum(float(value))}"


def prism_brush(pts, uvs, material, flags, face_id):
    """One SH polygon (CCW-from-front winding) -> TB brush lines.

    TB plane convention (vm::from_points): normal = cross(p3-p1, p2-p1), so
    plane points are wound clockwise seen from the front of the face.
    """
    n_raw = poly_normal(pts)
    nl = v_len(n_raw)
    if nl < 1e-6:
        return None
    n = v_scale(n_raw, 1.0 / nl)
    axes = solve_uv_axes(pts, uvs, n)
    if axes is None:
        return None
    e = v_scale(n, -THICKNESS)
    back = [v_add(p, e) for p in pts]

    lines = ["{"]
    # front: (v0, v2, v1) -> normal = cross(v1-v0, v2-v0) = +n for CCW pts
    lines.append(face_line(pts[0], pts[2], pts[1], material, axes, flags, face_id))
    # back: same index order on translated verts -> normal = -n
    lines.append(face_line(back[0], back[1], back[2], SKIP_MAT, None))
    # sides: (Vi, Vj, Vi+e) -> outward cross(edge, n)
    for i in range(len(pts)):
        j = (i + 1) % len(pts)
        lines.append(face_line(pts[i], pts[j], back[i], SKIP_MAT, None))
    lines.append("}")
    return lines


def quad_is_mergeable(pts, uvs):
    """True if the 4-corner polygon is planar, convex, and its UVs form one
    affine map (then a single quad face displays exactly like the two PSX tris)."""
    n = poly_normal(pts)
    nl = v_len(n)
    if nl < 1e-6:
        return False
    n = v_scale(n, 1.0 / nl)
    d = v_dot(pts[0], n)
    if any(abs(v_dot(p, n) - d) > EPS_PLANAR for p in pts):
        return False
    for i in range(4):  # convexity: all edge-cross products along +n
        a, b, c = pts[i], pts[(i + 1) % 4], pts[(i + 2) % 4]
        if v_dot(v_cross(v_sub(b, a), v_sub(c, b)), n) < 1e-9:
            return False
    axes = solve_uv_axes(pts[:3], uvs[:3], n)
    if axes is None:
        return False
    ua, uo, va, vo = axes
    return (abs(v_dot(pts[3], ua) + uo - uvs[3][0]) <= EPS_UV
            and abs(v_dot(pts[3], va) + vo - uvs[3][1]) <= EPS_UV)


# ---------- conversion ----------

def distinct_corners(prim):
    """PSX quad strip order (0,1,2,3) -> perimeter [0,1,3,2]; collapse repeats."""
    order = [0, 1, 3, 2]
    seen, corners = set(), []
    for c in order:
        vi = prim.vi[c]
        if vi != 0xFF and vi not in seen:
            seen.add(vi)
            corners.append(c)
    return corners


class Converter:
    def __init__(self, disc, gamedir, area, flip):
        self.bg = Path(disc) / "BG"
        self.gamedir = Path(gamedir)
        self.area = area.upper()
        self.flip = flip
        self.faces = {}          # id -> manifest record
        self.next_id = 1
        self.textures = {}       # (matname, clutrow) -> material path or None
        self.stats = {"brushes": 0, "quads_merged": 0, "quads_split": 0,
                      "tris": 0, "degenerate": 0, "billboards": 0}
        self.warnings = []

    def material_for(self, lm, prim, is_global):
        if prim.material_idx < 0:
            return UNTEX_MAT
        mat = lm.materials[prim.material_idx]
        row = prim.clut // 64
        key = (mat.name, row)
        if key not in self.textures:
            tim_path = self.bg / f"{mat.name}.TIM"
            if tim_path.exists():
                out = self.gamedir / "textures" / "bg" / f"{mat.name}_r{row:02d}.png"
                out.parent.mkdir(parents=True, exist_ok=True)
                Tim.parse(tim_path.read_bytes()).save_png(out, row)
                self.textures[key] = f"bg/{mat.name}_r{row:02d}"
            else:
                self.warnings.append(f"missing TIM {mat.name}.TIM")
                self.textures[key] = None
        return self.textures[key] or UNTEX_MAT

    def emit_prim(self, out, lm, model_name, mesh_idx, prim_idx, mesh, prim,
                  rot, trans, cell_off, ctx):
        corners = distinct_corners(prim)
        if len(corners) < 3:
            self.stats["degenerate"] += 1
            return
        world = {c: to_tb(transform_vertex(mesh.verts[prim.vi[c]], rot, trans, cell_off))
                 for c in corners}
        uvs = {c: (float(prim.uv[c][0]), float(prim.uv[c][1])) for c in corners}
        if self.flip:
            corners = corners[::-1]

        base_flags = (FLAG_TRANSPARENT if prim.is_transparent else 0) | ctx["flags"]

        def emit(cs, extra):
            pts = [world[c] for c in cs]
            uv = [uvs[c] for c in cs]
            mat = self.material_for(lm, prim, ctx["flags"] & FLAG_GLOBAL_PLM)
            fid = self.next_id
            brush = prism_brush(pts, uv, mat, base_flags | extra, fid)
            if brush is None:
                self.stats["degenerate"] += 1
                return
            self.next_id += 1
            out.extend(brush)
            self.stats["brushes"] += 1
            self.faces[fid] = {**ctx["prov"], "mesh": mesh_idx, "prim": prim_idx,
                               "corners": cs, "flags": base_flags | extra,
                               "model": model_name}

        if len(corners) == 4:
            if quad_is_mergeable([world[c] for c in corners], [uvs[c] for c in corners]):
                emit(corners, 0)
                self.stats["quads_merged"] += 1
            else:
                emit([corners[0], corners[1], corners[2]], 0)
                emit([corners[0], corners[2], corners[3]], FLAG_SECOND_HALF)
                self.stats["quads_split"] += 1
        else:
            emit(corners, 0)
            self.stats["tris"] += 1

    def convert(self):
        hexre = re.compile(rf"^{self.area}[0-9A-F]{{4}}$")
        ipd_files = sorted(p for p in self.bg.glob(f"{self.area}*.IPD")
                           if hexre.match(p.stem))
        if not ipd_files:
            raise SystemExit(f"no IPD cells found for area {self.area}")

        glb_path = self.bg / f"{self.area}_GLB.PLM"
        glb = Lm.parse(glb_path.read_bytes()) if glb_path.exists() else None

        maps_dir = self.gamedir / "maps"
        maps_dir.mkdir(parents=True, exist_ok=True)
        self.write_special_textures()

        out = ["// Game: Silent Hill",
               "// Format: Quake3 (Valve)",
               "{",
               '"classname" "worldspawn"',
               "}"]
        ent_id = 1
        billboard_ents = []
        cells_meta = {}

        for f in ipd_files:
            data = f.read_bytes()
            ipd = Ipd.parse(data)
            cell_off = (ipd.cell_x * CELL_Q8, ipd.cell_z * CELL_Q8)
            cells_meta[f.stem] = {
                "cellX": ipd.cell_x, "cellZ": ipd.cell_z, "size": len(data),
                "models": len(ipd.lm.models), "materials": len(ipd.lm.materials),
            }
            out.append("{")
            out.append('"classname" "func_group"')
            out.append('"_tb_type" "_tb_group"')
            out.append(f'"_tb_name" "{f.stem}"')
            out.append(f'"_tb_id" "{ent_id}"')
            ent_id += 1

            for buf_idx, buf in enumerate(ipd.model_buffers):
                for inst_idx, inst in enumerate(buf.instances):
                    info = ipd.model_infos[inst.model_info_idx]
                    if info.is_global_plm:
                        if glb is None:
                            self.warnings.append(f"{f.stem}: global model "
                                                 f"{info.name} but no GLB PLM")
                            continue
                        lm, flags = glb, FLAG_GLOBAL_PLM
                        container = f"{self.area}_GLB.PLM"
                    else:
                        lm, flags = ipd.lm, 0
                        container = f.name
                    model = lm.model_by_name(info.name)
                    if model is None:
                        self.warnings.append(f"{f.stem}: model {info.name!r} not found")
                        continue
                    prov = {"cell": f.stem, "container": container,
                            "buffer": buf_idx, "instance": inst_idx}
                    ctx = {"flags": flags, "prov": prov}
                    for mesh_idx, mesh in enumerate(model.meshes):
                        for prim_idx, prim in enumerate(mesh.prims):
                            self.emit_prim(out, lm, info.name, mesh_idx, prim_idx,
                                           mesh, prim, inst.rot, inst.trans,
                                           cell_off, ctx)

                for bb in buf.billboards:
                    p = to_tb((bb[0] + cell_off[0], bb[1], bb[2] + cell_off[1]))
                    billboard_ents.append(
                        "{\n" + '"classname" "sh_billboard"\n'
                        f'"origin" "{fnum(p[0])} {fnum(p[1])} {fnum(p[2])}"\n'
                        f'"bbtype" "{bb[3]}"\n' + f'"cell" "{f.stem}"\n' + "}")
                    self.stats["billboards"] += 1
            out.append("}")

        out.extend(billboard_ents)

        map_path = maps_dir / f"{self.area}.map"
        map_path.write_text("\n".join(out) + "\n", encoding="ascii")

        manifest = {
            "area": self.area, "scale_q8_per_tb": SCALE, "thickness_tb": THICKNESS,
            "axes": "tb = (sh.x, sh.z, -sh.y) / scale",
            "flip_winding": self.flip,
            "cells": cells_meta,
            "textures": {f"{k[0]}_r{k[1]:02d}": v for k, v in self.textures.items() if v},
            "faces": {str(k): v for k, v in self.faces.items()},
        }
        (maps_dir / f"{self.area}.manifest.json").write_text(
            json.dumps(manifest, indent=1), encoding="ascii")

        print(f"{self.area}: {len(ipd_files)} cells -> {map_path}")
        print(f"  brushes={self.stats['brushes']} "
              f"(quads merged={self.stats['quads_merged']} "
              f"split={self.stats['quads_split']} tris={self.stats['tris']} "
              f"degenerate skipped={self.stats['degenerate']})")
        print(f"  textures={len([v for v in self.textures.values() if v])} "
              f"billboards={self.stats['billboards']}")
        for w in sorted(set(self.warnings)):
            print(f"  WARN: {w}")

    def write_special_textures(self):
        from PIL import Image
        d = self.gamedir / "textures" / "special"
        d.mkdir(parents=True, exist_ok=True)
        skip = Image.new("RGBA", (64, 64), (80, 48, 96, 255))
        for x in range(64):
            skip.putpixel((x, x), (140, 90, 160, 255))
            skip.putpixel((x, 63 - x), (140, 90, 160, 255))
        skip.save(d / "skip.png")
        Image.new("RGBA", (64, 64), (200, 60, 60, 255)).save(d / "untextured.png")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--area", required=True, help="area tag, e.g. DRU, HP, THR")
    ap.add_argument("--disc", default=None,
                    help="extracted disc assets (dir containing BG/)")
    ap.add_argument("--gamedir", default=None,
                    help="output dir for maps/ and textures/")
    ap.add_argument("--flip-winding", action="store_true",
                    help="reverse front-face winding if faces come out inverted")
    args = ap.parse_args()
    from sh1fmt import paths
    Converter(paths.disc_dir(args.disc), paths.gamedir(args.gamedir),
              args.area, args.flip_winding).convert()


if __name__ == "__main__":
    main()
