"""Which maps use a texture? Replacement is keyed by the 8-char TIM NAME, so
before replacing a sheet, check who references it.

  python tim_owners.py DRU01F      # owners of one sheet
  python tim_owners.py --shared    # every sheet used by more than one area
  python tim_owners.py --area DRU  # every sheet the DRU area uses, with owners
"""

import re
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from sh1fmt import Ipd, Lm

BG = Path(r"C:\Claude\silenthill\disc_extract\BG")
AREAS = ["THR", "SPR", "SPU", "RSR", "RSU", "APR", "APU", "DRU", "DR",
         "SC", "SU", "ER", "HP", "HU"]
AREA_TO_MAPS = {
    "THR": "map0_s00 map0_s01 map2_s00 map2_s03",
    "SC": "map1_s00 map1_s01 map1_s06", "SU": "map1_s02-s05",
    "ER": "map0_s02 map2_s01 map2_s04 map4_s01 map5_s02 map5_s03 map6_s01 map7_s00-s03",
    "HP": "map3_s00 map3_s01 map3_s06", "HU": "map3_s02-s05 map4_s04",
    "SPR": "map2_s02 map4_s00 map4_s06", "SPU": "map4_s02 map4_s03 map4_s05",
    "RSR": "map5_s01", "RSU": "map6_s00 map6_s02", "DR": "map5_s00",
    "DRU": "map6_s03", "APU": "map6_s04 map6_s05", "APR": "(unused area)",
}


def area_of(stem):
    for a in sorted(AREAS, key=len, reverse=True):
        if re.fullmatch(rf"{a}[0-9A-F]{{4}}", stem):
            return a
    return None


def scan():
    refs = defaultdict(set)
    for f in sorted(BG.glob("*.IPD")):
        area = area_of(f.stem)
        if area is None:
            continue
        for m in Ipd.parse(f.read_bytes()).lm.materials:
            if m.name:
                refs[m.name].add(area)
    for f in sorted(BG.glob("*.PLM")):
        owner = f.stem[:-4] if f.stem.endswith("_GLB") else f.stem
        for m in Lm.parse(f.read_bytes()).materials:
            if m.name:
                refs[m.name].add(owner)
    return refs


def show(name, owners):
    maps = "; ".join(AREA_TO_MAPS.get(o, o) for o in sorted(owners))
    print(f"{name}: {sorted(owners)} -> {maps}")


def main():
    args = sys.argv[1:]
    refs = scan()
    if not args:
        print(__doc__)
    elif args[0] == "--shared":
        for name, owners in sorted(refs.items()):
            if len(owners) > 1:
                show(name, owners)
    elif args[0] == "--area" and len(args) > 1:
        area = args[1].upper()
        for name, owners in sorted(refs.items()):
            if area in owners:
                show(name, owners)
    else:
        name = args[0].upper()
        if name in refs:
            show(name, refs[name])
        else:
            print(f"{name}: not referenced by any map geometry")


if __name__ == "__main__":
    main()
