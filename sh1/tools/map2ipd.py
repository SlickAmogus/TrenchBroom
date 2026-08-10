"""Compile an edited TrenchBroom .map back into Silent Hill IPD files.

v1 supports SAME-TOPOLOGY edits, patched in place into copies of the original
IPDs (output size == original size, so the PC port's loose-file override
accepts them unconditionally):
  - retexture: face material bg/<TIM>_r<row> -> prim material_idx + clut,
    provided <TIM> is already in the owning LM's material list
  - UV realignment: new Valve axes evaluated at the prim's vertex positions
  - vertex moves: front-face polygon reconstructed from brush planes and
    written back through the inverse instance transform (single-instance,
    identity-scale models only)
  - sh_transparent surface flag -> prim isTransparent bit
Anything else (new brushes, deleted brushes, new textures) is reported and
skipped — that is the v2 full-recompile feature.

Usage:
  python map2ipd.py --map <AREA>.map [--manifest <AREA>.manifest.json]
                    [--disc C:/Claude/silenthill/disc_extract]
                    [--out <dir>]        # default: pc_port/build/gamedata/load/BG
                    [--allow-plm]        # permit edits to the shared _GLB.PLM
Run it from TrenchBroom via Run > Compile Map (RunTool with ${MAP_FULL_NAME}).
"""

import argparse
import json
import re
import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from sh1fmt import Ipd, Lm
from sh1fmt.ipd import IpdModelInfo, IpdModelInstance, IpdModelBuffer, CELL_Q8
from sh1fmt.lm import Material, ModelHeader, MeshHeader, Primitive
from sh1fmt.writer import write_ipd
from ipd2map import (SCALE, v_sub, v_add, v_dot, v_cross, v_len,
                     v_scale, solve3)

DEFAULT_OUT = r"C:\Claude\silenthill\silent-hill-decomp\pc_port\build\gamedata\load\BG"
INTERIOR_TAGS = {"SC", "SU", "ER", "HP", "HU"}
SLOT_CAP_INTERIOR = 90112
SLOT_CAP_EXTERIOR = 45056
IDENTITY_ROT = [(4096, 0, 0), (0, 4096, 0), (0, 0, 4096)]
MAX_MATERIALS = 64        # prim material_idx is 7-bit signed; -1 = untextured
MAX_PRIMS_PER_MESH = 60   # keeps verts/slots/normals under their u8 caps

FLOAT = r"[-+]?[0-9]*\.?[0-9]+(?:[eE][-+]?[0-9]+)?"
FACE_RE = re.compile(
    rf"^\s*\(\s*({FLOAT})\s+({FLOAT})\s+({FLOAT})\s*\)"
    rf"\s*\(\s*({FLOAT})\s+({FLOAT})\s+({FLOAT})\s*\)"
    rf"\s*\(\s*({FLOAT})\s+({FLOAT})\s+({FLOAT})\s*\)"
    rf'\s+("[^"]*"|\S+)'
    rf"\s*\[\s*({FLOAT})\s+({FLOAT})\s+({FLOAT})\s+({FLOAT})\s*\]"
    rf"\s*\[\s*({FLOAT})\s+({FLOAT})\s+({FLOAT})\s+({FLOAT})\s*\]"
    rf"\s+({FLOAT})\s+({FLOAT})\s+({FLOAT})"
    rf"(?:\s+(-?\d+)\s+(-?\d+)\s+({FLOAT}))?\s*$")
MAT_RE = re.compile(r"^bg/([A-Z0-9_]+)_r(\d+)$")


class Face:
    __slots__ = ("points", "material", "u_axis", "u_off", "v_axis", "v_off",
                 "x_scale", "y_scale", "contents", "flags", "value")

    def __init__(self, m):
        g = m.groups()
        f = [float(x) if x is not None else None for x in g[:9]]
        self.points = [tuple(f[0:3]), tuple(f[3:6]), tuple(f[6:9])]
        self.material = g[9].strip('"')
        self.u_axis = tuple(float(x) for x in g[10:13])
        self.u_off = float(g[13])
        self.v_axis = tuple(float(x) for x in g[14:17])
        self.v_off = float(g[17])
        self.x_scale = float(g[19])
        self.y_scale = float(g[20])
        self.contents = int(g[21]) if g[21] else 0
        self.flags = int(g[22]) if g[22] else 0
        self.value = float(g[23]) if g[23] else 0.0

    def uv_at(self, p):
        u = v_dot(p, self.u_axis) / self.x_scale + self.u_off
        v = v_dot(p, self.v_axis) / self.y_scale + self.v_off
        return u, v

    def plane(self):
        n = v_cross(v_sub(self.points[2], self.points[0]),
                    v_sub(self.points[1], self.points[0]))
        n = v_scale(n, 1.0 / max(v_len(n), 1e-12))
        return n, v_dot(n, self.points[0])


def parse_map(path):
    """Return (brushes, entities): brushes = list of [Face], entities = list of
    dicts of key/value (with brushes attached under '_brushes')."""
    ents, brushes = [], []
    cur_ent, cur_brush = None, None
    kv = re.compile(r'^\s*"([^"]*)"\s+"([^"]*)"\s*$')
    for line in Path(path).read_text(encoding="ascii", errors="replace").splitlines():
        s = line.strip()
        if s.startswith("//") or not s:
            continue
        if s == "{":
            if cur_ent is None:
                cur_ent = {"_brushes": []}
            else:
                cur_brush = []
            continue
        if s == "}":
            if cur_brush is not None:
                cur_ent["_brushes"].append(cur_brush)
                brushes.append(cur_brush)
                cur_brush = None
            else:
                ents.append(cur_ent)
                cur_ent = None
            continue
        if cur_brush is not None:
            m = FACE_RE.match(s)
            if m:
                cur_brush.append(Face(m))
            continue
        m = kv.match(s)
        if m and cur_ent is not None:
            cur_ent[m.group(1)] = m.group(2)
    return brushes, ents


def polygon_of_face(brush, face, eps=0.01):
    """Vertices of `face` on the convex brush: triple-plane intersections that
    lie on the face plane and inside all planes, ordered around the centroid."""
    planes = [f.plane() for f in brush]
    fn, fd = face.plane()
    pts = []
    n = len(planes)
    for i in range(n):
        for j in range(i + 1, n):
            m = (fn, planes[i][0], planes[j][0])
            p = solve3(m, (fd, planes[i][1], planes[j][1]))
            if p is None:
                continue
            if all(v_dot(pn, p) <= pd + eps for pn, pd in planes):
                if not any(v_len(v_sub(p, q)) < eps for q in pts):
                    pts.append(p)
    if len(pts) < 3:
        return None
    c = v_scale([sum(p[i] for p in pts) for i in range(3)], 1.0 / len(pts))
    ref = v_sub(pts[0], c)
    ref = v_scale(ref, 1.0 / max(v_len(ref), 1e-12))
    up = v_cross(fn, ref)

    def ang(p):
        d = v_sub(p, c)
        import math
        return math.atan2(v_dot(d, up), v_dot(d, ref))
    return sorted(pts, key=ang)


def tb_to_sh_q8(p):
    return (p[0] * SCALE, -p[2] * SCALE, p[1] * SCALE)


class Compiler:
    def __init__(self, args):
        self.disc = Path(args.disc)
        self.out = Path(args.out)
        self.allow_plm = args.allow_plm
        self.full = getattr(args, "full", False)
        map_path = Path(args.map)
        self.area = map_path.stem.upper()
        manifest_path = Path(args.manifest) if args.manifest else \
            map_path.with_name(f"{map_path.stem}.manifest.json")
        self.manifest = json.loads(manifest_path.read_text())
        self.area = self.manifest.get("area", self.area)
        self.brushes, self.ents = parse_map(map_path)
        self.containers = {}      # filename -> {"data": bytearray, "pristine", "parsed", "dirty"}
        self.instance_count = {}  # (container, model) -> instances in whole area
        self.stats = {"retextured": 0, "uv": 0, "verts_moved": 0, "flags": 0,
                      "prims_deleted": 0, "prims_added": 0, "materials_added": 0}
        self.skipped = []
        self.deleted_fids = set()     # --full: faces removed in the editor
        self.deferred_retex = []      # --full: (rec, tim, row, fid) needing new material

    # ---------- container access ----------

    def container(self, name):
        if name not in self.containers:
            raw = (self.disc / "BG" / name).read_bytes()
            parsed = Ipd.parse(raw) if name.endswith(".IPD") else Lm.parse(raw)
            self.containers[name] = {"data": bytearray(raw), "pristine": raw,
                                     "parsed": parsed, "dirty": False}
        return self.containers[name]

    def lm_of(self, cont):
        p = cont["parsed"]
        return p.lm if isinstance(p, Ipd) else p

    def resolve(self, rec):
        """Manifest record -> (container, lm, model, mesh, prim, instance)."""
        cont = self.container(rec["container"])
        lm = self.lm_of(cont)
        model = lm.model_by_name(rec["model"])
        mesh = model.meshes[rec["mesh"]]
        prim = mesh.prims[rec["prim"]]
        cell = self.container(rec["cell"] + ".IPD")["parsed"]
        inst = cell.model_buffers[rec["buffer"]].instances[rec["instance"]]
        return cont, lm, model, mesh, prim, inst, cell

    # ---------- patches ----------

    def patch_u8(self, cont, off, val, what):
        v = int(round(val))
        if not 0 <= v <= 255:
            raise ValueError(f"{what} {val:.1f} outside 0..255")
        if cont["data"][off] != v:
            cont["data"][off] = v
            cont["dirty"] = True
            return True
        return False

    def patch_u16(self, cont, off, val):
        if struct.unpack_from("<H", cont["data"], off)[0] != val:
            struct.pack_into("<H", cont["data"], off, val)
            cont["dirty"] = True
            return True
        return False

    def apply_face(self, rec, face, corner_uvs, id_):
        cont, lm, model, mesh, prim, inst, cell = self.resolve(rec)
        if rec["container"].endswith(".PLM") and not self.allow_plm:
            self.skipped.append(f"face {id_}: edits shared {rec['container']} "
                                f"(pass --allow-plm to permit)")
            return
        p_off = prim.file_off

        # material + clut
        m = MAT_RE.match(face.material)
        if m:
            tim, row = m.group(1), int(m.group(2))
            mat_idx = next((i for i, mt in enumerate(lm.materials) if mt.name == tim), None)
            if mat_idx is None:
                if self.full and rec["container"].endswith(".IPD"):
                    self.deferred_retex.append((rec, tim, row, id_))
                else:
                    self.skipped.append(f"face {id_}: TIM {tim} not in material list "
                                        f"of {rec['container']} (use --full to add)")
            else:
                field6 = struct.unpack_from("<H", cont["data"], p_off + 6)[0]
                new6 = (field6 & 0x80FF) | ((mat_idx & 0x7F) << 8)
                transparent = bool(int(rec.get("flags", 0)) & 1)
                if face.flags & 1 != (new6 >> 15):
                    new6 = (new6 & 0x7FFF) | ((face.flags & 1) << 15)
                    self.stats["flags"] += 1
                if self.patch_u16(cont, p_off + 6, new6):
                    self.stats["retextured"] += 1
                if self.patch_u16(cont, p_off + 2, row * 64):
                    self.stats["retextured"] += 1
        elif face.material not in ("special/untextured", "special/skip"):
            self.skipped.append(f"face {id_}: unrecognized material {face.material}")

        # UVs at the prim's (possibly moved) vertices
        uv_offsets = {0: p_off + 0, 1: p_off + 4, 2: p_off + 8, 3: p_off + 10}
        for corner, (u, v) in corner_uvs.items():
            off = uv_offsets[corner]
            try:
                if self.patch_u8(cont, off, u, f"face {id_} u"):
                    self.stats["uv"] += 1
                if self.patch_u8(cont, off + 1, v, f"face {id_} v"):
                    self.stats["uv"] += 1
            except ValueError as e:
                self.skipped.append(str(e))

    def apply_vertex(self, rec, vi, tb, id_):
        """Write one mesh vertex (model-local s16 Q8) from a TB-space position."""
        cont, lm, model, mesh, prim, inst, cell = self.resolve(rec)
        key = (rec["container"], rec["model"])
        if self.instance_count.get(key, 0) > 1:
            self.skipped.append(f"face {id_}: model {rec['model']} has multiple "
                                f"instances; vertex moves need v2")
            return
        # invert instance transform: rotation Q12 assumed orthonormal
        r = inst.rot
        cell_off = (cell.cell_x * CELL_Q8, cell.cell_z * CELL_Q8)
        w = tb_to_sh_q8(tb)
        local_w = (w[0] - inst.trans[0] - cell_off[0],
                   w[1] - inst.trans[1],
                   w[2] - inst.trans[2] - cell_off[1])
        # v = R^T . local (R rows are world<-model)
        v = tuple(sum(r[k][i] * local_w[k] for k in range(3)) / 4096.0
                  for i in range(3))
        xy_off = mesh.verts_xy_off + vi * 4
        z_off = mesh.verts_z_off + vi * 2
        vals = tuple(int(round(c)) for c in v)
        if any(not -32768 <= c <= 32767 for c in vals):
            self.skipped.append(f"face {id_}: vertex {vi} out of s16 range")
            return
        old = struct.unpack_from("<hh", cont["data"], xy_off) + \
            struct.unpack_from("<h", cont["data"], z_off)
        if old != vals:
            struct.pack_into("<hh", cont["data"], xy_off, vals[0], vals[1])
            struct.pack_into("<h", cont["data"], z_off, vals[2])
            cont["dirty"] = True
            self.stats["verts_moved"] += 1

    # ---------- main ----------

    def run(self):
        faces_by_id = {}
        for brush in self.brushes:
            for face in brush:
                fid = int(round(face.value))
                if fid > 0:
                    faces_by_id[fid] = (brush, face)

        # instance census for the multi-instance guard
        for rec in self.manifest["faces"].values():
            pass
        for cell_name in self.manifest["cells"]:
            ipd = self.container(cell_name + ".IPD")["parsed"]
            for buf in ipd.model_buffers:
                for inst in buf.instances:
                    info = ipd.model_infos[inst.model_info_idx]
                    cname = f"{self.area}_GLB.PLM" if info.is_global_plm else cell_name + ".IPD"
                    key = (cname, info.name)
                    self.instance_count[key] = self.instance_count.get(key, 0) + 1

        # Phase A: reconstruct every face polygon, match corners against the
        # PRISTINE geometry, and collect vertex-move proposals + face patches.
        # Order-independent: faces whose brushes were not moved propose nothing,
        # even when a neighbouring edit moves a vertex their prim shares.
        proposals = {}   # (container, model, mesh_idx, vertex_idx) -> (pos, fid)
        face_jobs = []   # (rec, face, {corner: uv}, fid)
        seen_prims = {}
        for fid_s, rec in self.manifest["faces"].items():
            fid = int(fid_s)
            hit = faces_by_id.get(fid)
            if hit is None:
                if self.full:
                    self.deleted_fids.add(fid)
                else:
                    self.skipped.append(
                        f"face {fid}: deleted in editor (use --full)")
                continue
            brush, face = hit
            poly = polygon_of_face(brush, face)
            if poly is None:
                self.skipped.append(f"face {fid}: could not reconstruct polygon")
                continue

            cont, lm, model, mesh, prim, inst, cell = self.resolve(rec)
            cell_off = (cell.cell_x * CELL_Q8, cell.cell_z * CELL_Q8)

            def tb_of(vi):
                v = struct.unpack_from("<hh", cont["pristine"], mesh.verts_xy_off + vi * 4) \
                    + struct.unpack_from("<h", cont["pristine"], mesh.verts_z_off + vi * 2)
                r = inst.rot
                w = [sum(r[i][k] * v[k] for k in range(3)) / 4096.0 for i in range(3)]
                w[0] += inst.trans[0] + cell_off[0]
                w[1] += inst.trans[1]
                w[2] += inst.trans[2] + cell_off[1]
                return (w[0] / SCALE, w[2] / SCALE, -w[1] / SCALE)

            corners = rec["corners"]
            expect = {c: tb_of(prim.vi[c]) for c in corners}

            # match reconstructed polygon vertices to corners (nearest, unique)
            corner_pos = {}
            used = set()
            for c in corners:
                best, bd = None, 1e18
                for k, p in enumerate(poly):
                    if k in used:
                        continue
                    d = v_len(v_sub(p, expect[c]))
                    if d < bd:
                        best, bd = k, d
                used.add(best)
                corner_pos[c] = poly[best]
                if bd > 0.05:
                    vkey = (rec["container"], rec["model"], rec["mesh"], prim.vi[c])
                    prev = proposals.get(vkey)
                    if prev and v_len(v_sub(prev[0], poly[best])) > 0.05:
                        self.skipped.append(
                            f"face {fid}: vertex {prim.vi[c]} conflicts with edit "
                            f"from face {prev[1]}; keeping face {prev[1]}'s position")
                    else:
                        proposals[vkey] = (poly[best], fid)

            key = (rec["container"], rec["model"], rec["mesh"], rec["prim"])
            corner_uvs = seen_prims.setdefault(key, {})
            for c in corners:
                u, v = face.uv_at(corner_pos[c])
                if c in corner_uvs and (abs(corner_uvs[c][0] - u) > 0.51
                                        or abs(corner_uvs[c][1] - v) > 0.51):
                    self.skipped.append(f"face {fid}: split-quad halves disagree on "
                                        f"corner {c} UV; using first half")
                else:
                    corner_uvs[c] = (u, v)
            face_jobs.append((rec, face, corners, key, fid))

        # Phase B: apply vertex moves once, conflict-free.
        for (cname, mname, mesh_idx, vi), (pos, fid) in proposals.items():
            rec = next(r for r, _, _, _, f in face_jobs
                       if f == fid)
            self.apply_vertex(rec, vi, pos, fid)

        # Phase C: apply material/UV/flag patches.
        for rec, face, corners, key, fid in face_jobs:
            corner_uvs = seen_prims[key]
            self.apply_face(rec, face, {c: corner_uvs[c] for c in corners
                                        if c in corner_uvs}, fid)

        self.out.mkdir(parents=True, exist_ok=True)
        if self.full:
            written = self.run_full()
        else:
            written = []
            for name, cont in self.containers.items():
                if cont["dirty"]:
                    orig = (self.disc / "BG" / name).stat().st_size
                    assert len(cont["data"]) == orig, f"{name}: size changed!"
                    (self.out / name).write_bytes(bytes(cont["data"]))
                    written.append(name)

        print(f"map2ipd {self.area}: retexture={self.stats['retextured']} "
              f"uvBytes={self.stats['uv']} vertsMoved={self.stats['verts_moved']} "
              f"transparencyFlags={self.stats['flags']}"
              + (f" primsDeleted={self.stats['prims_deleted']} "
                 f"primsAdded={self.stats['prims_added']} "
                 f"materialsAdded={self.stats['materials_added']}"
                 if self.full else ""))
        print(f"written: {written if written else 'nothing (no changes)'} -> {self.out}")
        self.report_skips()
        return 0

    def report_skips(self):
        """Collapse repeated skips to their shared reason. Thousands of
        identical per-face messages (a shared PLM, a missing material) would
        otherwise bury the one-off errors that actually need attention."""
        groups = {}
        for s in self.skipped:
            # strip the leading "face <n>: " / "<CELL>: " subject
            reason = re.sub(r"^(face \d+|[A-Z0-9_]+): ", "", s)
            groups.setdefault(reason, []).append(s)
        for reason, items in sorted(groups.items(), key=lambda kv: -len(kv[1])):
            if len(items) == 1:
                print(f"  SKIP: {items[0]}")
            else:
                subjects = [re.match(r"^(face \d+|[A-Z0-9_]+):", i) for i in items]
                names = [m.group(1) for m in subjects if m][:3]
                more = f" (+{len(items) - len(names)} more)" if len(items) > len(names) else ""
                print(f"  SKIP x{len(items)}: {reason}")
                print(f"          e.g. {', '.join(names)}{more}")

    # ---------- --full: topology-changing recompile ----------

    def new_brushes_by_cell(self):
        """ID-less brushes with textured faces, assigned to an IPD cell by their
        TrenchBroom group name, else by centroid."""
        cells = self.manifest["cells"]
        by_cell = {}
        for ent in self.ents:
            group = ent.get("_tb_name", "")
            for brush in ent["_brushes"]:
                if any(int(round(f.value)) > 0 for f in brush):
                    continue
                faces = [f for f in brush if f.material.startswith("bg/")
                         or f.material == "special/untextured"]
                if not faces:
                    continue
                cell = group if group in cells else None
                if cell is None:
                    pts = [p for f in brush for p in f.points]
                    cx = int((sum(p[0] for p in pts) / len(pts)) * SCALE // CELL_Q8)
                    cz = int((sum(p[1] for p in pts) / len(pts)) * SCALE // CELL_Q8)
                    cell = next((n for n, c in cells.items()
                                 if c["cellX"] == cx and c["cellZ"] == cz), None)
                if cell is None:
                    self.skipped.append("new brush outside every cell of this "
                                        "area; skipped")
                    continue
                by_cell.setdefault(cell, []).append((brush, faces))
        return by_cell

    def build_new_models(self, ipd, cell_name, brush_faces, lm, next_seq):
        """Pack new textured faces into fresh single-mesh models; returns the
        number of prims added."""
        cell_off = (ipd.cell_x * CELL_Q8, ipd.cell_z * CELL_Q8)
        pending = []   # (corners_sh, uvs, mat_idx, transparent)
        for brush, faces in brush_faces:
            for face in faces:
                poly = polygon_of_face(brush, face)
                if poly is None or len(poly) < 3:
                    self.skipped.append(f"{cell_name}: new face polygon "
                                        f"degenerate; skipped")
                    continue
                mat_idx = -1
                m = MAT_RE.match(face.material)
                if m:
                    tim, row = m.group(1), int(m.group(2))
                    mat_idx = next((i for i, mt in enumerate(lm.materials)
                                    if mt.name == tim), None)
                    if mat_idx is None:
                        self.skipped.append(f"{cell_name}: material {tim} "
                                            f"unavailable; face untextured")
                        mat_idx = -1
                # triangulate polygons with >4 corners (fan)
                rings = [poly] if len(poly) <= 4 else \
                    [[poly[0], poly[i], poly[i + 1]] for i in range(1, len(poly) - 1)]
                for ring in rings:
                    sh = []
                    for p in ring:
                        w = tb_to_sh_q8(p)
                        sh.append((int(round(w[0] - cell_off[0])),
                                   int(round(w[1])),
                                   int(round(w[2] - cell_off[1]))))
                    if any(not -32768 <= c <= 32767 for v in sh for c in v):
                        self.skipped.append(f"{cell_name}: new face vertex out "
                                            f"of s16 range; skipped")
                        continue
                    uvs = []
                    for p in ring:
                        u, v = face.uv_at(p)
                        uvs.append((max(0, min(255, int(round(u)))),
                                    max(0, min(255, int(round(v))))))
                    row_clut = int(m.group(2)) * 64 if (m and mat_idx >= 0) else 0
                    pending.append((sh, uvs, mat_idx, row_clut,
                                    1 if int(round(face.flags)) & 1 else 0))

        added = 0
        for chunk_start in range(0, len(pending), MAX_PRIMS_PER_MESH):
            chunk = pending[chunk_start:chunk_start + MAX_PRIMS_PER_MESH]
            verts, vmap = [], {}
            prims, normals, slots = [], [], bytearray()

            def vert_idx(v):
                if v not in vmap:
                    vmap[v] = len(verts)
                    verts.append(v)
                return vmap[v]

            for sh, uvs, mat_idx, clut, transp in chunk:
                # perimeter (CCW from front) -> PSX strip order (0,1,3,2);
                # triangles repeat the last strip index (retail convention)
                per = [vert_idx(v) for v in sh]
                if len(per) == 4:
                    vi = (per[0], per[1], per[3], per[2])
                    uv = (uvs[0], uvs[1], uvs[3], uvs[2])
                else:
                    vi = (per[0], per[1], per[2], per[2])
                    uv = (uvs[0], uvs[1], uvs[2], uvs[2])
                # one flat normal per prim; slots are vertex indices
                e1 = v_sub(sh[1], sh[0])
                e2 = v_sub(sh[2], sh[0])
                n = v_cross(e1, e2)
                ln = v_len(n) or 1.0
                n8 = tuple(max(-127, min(127, int(round(c * 127.0 / ln)))) for c in n)
                if n8 == (0, 0, 0):
                    n8 = (0, -127, 0)
                corner_n = len(set(vi))
                li = []
                for k in range(corner_n):
                    li.append(len(slots))
                    slots.append(vi[k])
                while len(li) < 4:
                    li.append(li[-1])
                normals.append((n8[0], n8[1], n8[2], corner_n))
                prims.append(Primitive(uv, clut, 0, mat_idx, transp, vi,
                                       tuple(li), 0))
                added += 1

            mesh = MeshHeader(len(prims), len(verts), len(normals), len(slots),
                              prims, verts, normals, bytes(slots), 0, 0, 0)
            name = f"TB{next_seq:05d}"[:8]
            next_seq += 1
            lm.models.append(ModelHeader(name, 1, 0, 0, 0, [mesh]))
            lm.model_order += bytes([len(lm.models) - 1])
            ipd.model_infos.append(IpdModelInfo(0, name))
        return added, next_seq

    def run_full(self):
        """Recompile every cell structurally: deferred retextures on new
        materials, prim deletions, new brushes as new models, then serialize
        through the byte-exact writer."""
        new_by_cell = self.new_brushes_by_cell()
        interior = self.area in INTERIOR_TAGS
        cap = SLOT_CAP_INTERIOR if interior else SLOT_CAP_EXTERIOR
        written = []

        # prim -> [face ids], for the both-halves deletion rule
        prim_fids = {}
        for fid_s, rec in self.manifest["faces"].items():
            key = (rec["container"], rec["model"], rec["mesh"], rec["prim"])
            prim_fids.setdefault(key, []).append(int(fid_s))

        for cell_name in self.manifest["cells"]:
            name = cell_name + ".IPD"
            cont = self.container(name)
            ipd = Ipd.parse(bytes(cont["data"]))
            lm = ipd.lm
            changed = cont["dirty"]
            topo = False

            # 1. new materials (deferred retextures + new-brush needs)
            needed = {}
            for rec, tim, row, fid in self.deferred_retex:
                if rec["container"] == name:
                    needed.setdefault(tim, []).append((rec, row, fid))
            for tim in list(needed) + [
                    m.group(1)
                    for _, faces in new_by_cell.get(cell_name, [])
                    for f in faces
                    if (m := MAT_RE.match(f.material))]:
                if any(mt.name == tim for mt in lm.materials):
                    continue
                if not (self.disc / "BG" / f"{tim}.TIM").exists():
                    self.skipped.append(f"{cell_name}: no such TIM {tim}")
                    needed.pop(tim, None)
                    continue
                if len(lm.materials) >= MAX_MATERIALS:
                    self.skipped.append(f"{cell_name}: material list full "
                                        f"({MAX_MATERIALS}); cannot add {tim}")
                    needed.pop(tim, None)
                    continue
                lm.materials.append(Material(tim, 0, 0, 0))
                self.stats["materials_added"] += 1
                changed = True

            # 2. deferred retextures, structurally
            for tim, entries in needed.items():
                idx = next((i for i, mt in enumerate(lm.materials)
                            if mt.name == tim), None)
                if idx is None:
                    continue
                for rec, row, fid in entries:
                    model = lm.model_by_name(rec["model"])
                    prim = model.meshes[rec["mesh"]].prims[rec["prim"]]
                    prim.material_idx = idx
                    prim.clut = row * 64
                    self.stats["retextured"] += 1
                    changed = True

            # 3. deletions (a prim goes only when ALL its faces were deleted)
            doomed = {}
            for (cname, mname, mesh_i, prim_i), fids in prim_fids.items():
                if cname != name:
                    continue
                gone = [f for f in fids if f in self.deleted_fids]
                if not gone:
                    continue
                if len(gone) < len(fids):
                    self.skipped.append(
                        f"{cell_name}: only one half of prim "
                        f"{mname}/{mesh_i}/{prim_i} deleted; keeping it")
                    continue
                doomed.setdefault((mname, mesh_i), []).append(prim_i)
            for (mname, mesh_i), prim_idxs in doomed.items():
                model = lm.model_by_name(mname)
                for pi in sorted(prim_idxs, reverse=True):
                    del model.meshes[mesh_i].prims[pi]
                    self.stats["prims_deleted"] += 1
                changed = topo = True

            # 4. new brushes -> new models + one shared buffer
            if cell_name in new_by_cell:
                seq = 0
                n_before = len(lm.models)
                added, seq = self.build_new_models(
                    ipd, cell_name, new_by_cell[cell_name], lm, seq)
                if added:
                    self.stats["prims_added"] += added
                    instances = [
                        IpdModelInstance(len(ipd.model_infos) - (len(lm.models) - n_before) + k,
                                         IDENTITY_ROT, (0, 0, 0), 0)
                        for k in range(len(lm.models) - n_before)]
                    ipd.model_buffers.append(IpdModelBuffer(
                        len(instances), 0, 1, (0, CELL_Q8, 0, CELL_Q8),
                        instances, [], [(0, CELL_Q8, 0, CELL_Q8)]))
                    ipd.model_order += bytes([len(ipd.model_buffers) - 1])
                    changed = topo = True

            if topo:
                # conservative draw table: every subcell draws every buffer
                n = len(ipd.model_order)
                ipd.draw_table = bytes([0, n] * 25)

            if not changed:
                continue

            body = write_ipd(ipd)
            out_bytes = body + bytes((-len(body)) % 256)
            orig_size = len(cont["pristine"])
            if out_bytes == cont["pristine"]:
                continue
            if len(out_bytes) > orig_size:
                print(f"  WARNING {name}: output {len(out_bytes)} B exceeds the "
                      f"original file size {orig_size} B - the PC port CANNOT "
                      f"load this until the file-table/size-cap work lands "
                      f"(docs/PC_PORT_INTEGRATION.md)")
            if len(out_bytes) > cap:
                print(f"  WARNING {name}: output {len(out_bytes)} B exceeds the "
                      f"{'interior' if interior else 'exterior'} chunk-slot cap "
                      f"{cap} B - the game cannot stream it even after the "
                      f"file-table fix")
            (self.out / name).write_bytes(out_bytes)
            written.append(name)
        return written


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--map", required=True)
    ap.add_argument("--manifest", default=None)
    ap.add_argument("--disc", default=r"C:\Claude\silenthill\disc_extract")
    ap.add_argument("--out", default=DEFAULT_OUT)
    ap.add_argument("--allow-plm", action="store_true")
    ap.add_argument("--full", action="store_true",
                    help="topology-changing recompile: new/deleted brushes and "
                         "new materials; output size may exceed the original "
                         "(see docs/PC_PORT_INTEGRATION.md for port support)")
    args = ap.parse_args()
    sys.exit(Compiler(args).run())


if __name__ == "__main__":
    main()
