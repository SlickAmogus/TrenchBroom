"""Parse every retail IPD/PLM/TIM in disc_extract and assert the invariants the
converter relies on. Run: python validate_formats.py [disc_extract_dir]"""

import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from sh1fmt import Ipd, Lm, Tim

from sh1fmt import paths
BG = paths.bg_dir(sys.argv[1] if len(sys.argv) > 1 else None)


def check_lm(lm, stats, src):
    mat_n = len(lm.materials)
    for model in lm.models:
        for mesh in model.meshes:
            for p in mesh.prims:
                stats["prims"] += 1
                assert p.clut % 64 == 0, f"{src}: clut {p.clut} not row*64"
                assert p.tpage == 0, f"{src}: nonzero disc tpage {p.tpage}"
                assert p.material_idx == -1 or p.material_idx < mat_n, \
                    f"{src}: material_idx {p.material_idx} >= {mat_n}"
                if p.material_idx == -1:
                    stats["untextured"] += 1
                distinct = []
                for v in p.vi:
                    if v == 0xFF:
                        stats["ff_sentinel"] += 1
                        continue
                    assert v < mesh.vertex_count, f"{src}: vi {v} >= {mesh.vertex_count}"
                    if v not in distinct:
                        distinct.append(v)
                stats["tris" if len(distinct) == 3 else "quads" if len(distinct) == 4
                      else "degenerate"] += 1
                for l in p.li:
                    assert l < max(mesh.lighting_slot_count, 1), \
                        f"{src}: li {l} >= {mesh.lighting_slot_count}"
                if p.is_transparent:
                    stats["transparent"] += 1
            assert sum(n[3] for n in mesh.normals) == mesh.lighting_slot_count, \
                f"{src}: normal counts != slot count"
            for s in mesh.lighting_slots:
                assert s < mesh.vertex_count, f"{src}: slot byte {s} >= vertex count"
    stats["materials"] += mat_n
    stats["models"] += len(lm.models)


def main():
    stats = Counter()
    errors = []

    ipds = sorted(BG.glob("*.IPD"))
    for f in ipds:
        try:
            ipd = Ipd.parse(f.read_bytes())
            xx, zz = f.stem[-4:-2], f.stem[-2:]
            assert ipd.cell_x == int(xx, 16) - (256 if int(xx, 16) > 127 else 0), \
                f"cellX {ipd.cell_x} != filename {xx}"
            assert ipd.cell_z == int(zz, 16) - (256 if int(zz, 16) > 127 else 0), \
                f"cellZ {ipd.cell_z} != filename {zz}"
            for buf in ipd.model_buffers:
                for inst in buf.instances:
                    assert inst.model_info_idx < len(ipd.model_infos), \
                        f"instance model idx {inst.model_info_idx} OOB"
            for o in ipd.model_order:
                assert o < len(ipd.model_buffers), f"order entry {o} OOB"
            check_lm(ipd.lm, stats, f.name)
            stats["ipd_ok"] += 1
            stats["global_refs"] += sum(i.is_global_plm for i in ipd.model_infos)
        except Exception as e:
            errors.append(f"{f.name}: {e}")

    for f in sorted(BG.glob("*.PLM")):
        try:
            check_lm(Lm.parse(f.read_bytes()), stats, f.name)
            stats["plm_ok"] += 1
        except Exception as e:
            errors.append(f"{f.name}: {e}")

    for f in sorted(BG.glob("*.TIM")):
        try:
            tim = Tim.parse(f.read_bytes())
            assert tim.pmode == 0, f"non-4bpp map TIM pmode {tim.pmode}"
            assert tim.clut_w == 16, f"clut width {tim.clut_w}"
            assert tim.width in (128, 256), f"width {tim.width}"
            stats["tim_ok"] += 1
            stats[f"tim_{tim.width}w"] += 1
        except Exception as e:
            errors.append(f"{f.name}: {e}")

    print(f"IPD parsed OK: {stats['ipd_ok']}/{len(ipds)}")
    print(f"PLM parsed OK: {stats['plm_ok']}")
    print(f"TIM parsed OK: {stats['tim_ok']} "
          f"(256w={stats['tim_256w']}, 128w={stats['tim_128w']})")
    print(f"models={stats['models']} materials={stats['materials']} "
          f"prims={stats['prims']} quads={stats['quads']} tris={stats['tris']} "
          f"degenerate={stats['degenerate']} ff={stats['ff_sentinel']}")
    print(f"untextured={stats['untextured']} transparent={stats['transparent']} "
          f"globalPlmRefs={stats['global_refs']}")
    if errors:
        print(f"\n{len(errors)} ERRORS:")
        for e in errors[:40]:
            print(" ", e)
        sys.exit(1)
    print("ALL INVARIANTS HOLD")


if __name__ == "__main__":
    main()
