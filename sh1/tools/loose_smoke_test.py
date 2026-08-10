"""Smoke-test the PC port's loose-file loader (which has never been exercised).

Generates test files into the port's gamedata/load/BG/ in three stages of
increasing signal. Run one stage, launch the game, visit the otherworld sewer
(map6_s03), observe, then move to the next.

  python loose_smoke_test.py 1   # unmodified DRU0000.IPD copy
                                 #   -> sewer looks NORMAL = loader path works
                                 #   -> corruption/crash = loader bug
  python loose_smoke_test.py 2   # DRU01F.TIM with a red 64x64 square
                                 #   -> red square on sewer walls = TIM loose
                                 #      replacement works end to end
  python loose_smoke_test.py 3   # DRU0000.IPD with the water-surface prim
                                 #   retextured + one quad raised 0.25 units
                                 #   -> visible change = full editor->game loop
  python loose_smoke_test.py clean   # remove all test files

Prerequisites: allow_loose_files = 1 in the port's config.cfg, and the game
must run with its working directory at the build dir (the loose path is
CWD-relative — launching the exe directly from its own folder is safe).
"""

import shutil
import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from sh1fmt import Tim

from sh1fmt import paths

BG = paths.bg_dir()
LOOSE = paths.loose_bg_dir()


def stage1():
    LOOSE.mkdir(parents=True, exist_ok=True)
    shutil.copy2(BG / "DRU0000.IPD", LOOSE / "DRU0000.IPD")
    print(f"stage 1: unmodified DRU0000.IPD -> {LOOSE}")
    print("expect: sewer entrance area renders EXACTLY as normal.")
    print("check SilentHill.log for the loose-file hit line (SH_LOOSE_VERBOSE=1).")


def stage2():
    """Stripe EVERY DRU sheet red so the signal is visible from anywhere in the
    sewer — a single painted patch on one sheet can end up in one far corner
    of the map depending on which faces sample those texels."""
    LOOSE.mkdir(parents=True, exist_ok=True)
    import subprocess
    from PIL import Image
    for tim_path in sorted(BG.glob("DRU*.TIM")):
        tim = Tim.parse(tim_path.read_bytes())
        rgba, _ = tim.rgba_for_clut_row(0)
        img = Image.frombytes("RGBA", (tim.width, tim.height), rgba)
        for y in range(0, tim.height, 32):
            for yy in range(y, min(y + 8, tim.height)):
                for x in range(tim.width):
                    if img.getpixel((x, yy))[3]:  # keep transparency intact
                        img.putpixel((x, yy), (248, 0, 0, 255))
        tmp = LOOSE / "_stripe.png"
        img.save(tmp)
        subprocess.run([sys.executable, str(Path(__file__).parent / "png2tim.py"),
                        "--png", str(tmp), "--tim", str(tim_path),
                        "-o", str(LOOSE / tim_path.name)], check=True,
                       capture_output=True)
        print(f"  striped {tim_path.name}")
    tmp.unlink()
    print("stage 2: ALL DRU sheets striped red -> every wall/floor/ceiling in "
          "the sewer should show horizontal red bands. Re-enter the area to "
          "reload chunks.")


def stage3():
    LOOSE.mkdir(parents=True, exist_ok=True)
    # replicate the validated 13-byte edit: water prim 0 retextured to DRUG02
    # (material idx 5) and prim 1's quad raised by 64 Q8 (0.25 units)
    from sh1fmt import Ipd
    raw = bytearray((BG / "DRU0000.IPD").read_bytes())
    ipd = Ipd.parse(bytes(raw))
    model = ipd.lm.model_by_name("NAMI2_DW")
    mesh = model.meshes[0]
    p0 = mesh.prims[0]
    field6 = struct.unpack_from("<H", raw, p0.file_off + 6)[0]
    struct.pack_into("<H", raw, p0.file_off + 6, (field6 & 0x80FF) | (5 << 8))
    struct.pack_into("<H", raw, p0.file_off + 2, 0)
    p1 = mesh.prims[1]
    for vi in set(p1.vi):
        xy = mesh.verts_xy_off + vi * 4
        x, y = struct.unpack_from("<hh", raw, xy)
        struct.pack_into("<hh", raw, xy, x, y - 64)
    (LOOSE / "DRU0000.IPD").write_bytes(bytes(raw))
    print("stage 3: DRU0000.IPD edit -> water surface tile retextured to wall "
          "texture + one tile raised 0.25 units, at the sewer entrance cell.")


def clean():
    """Remove every file any stage can produce. Stage 2 writes one TIM per DRU
    sheet, so a fixed filename list would strand a dozen striped textures in the
    live game."""
    removed = 0
    for p in sorted(LOOSE.glob("DRU*.IPD")) + sorted(LOOSE.glob("DRU*.TIM")) \
            + sorted(LOOSE.glob("_stripe.png")):
        p.unlink()
        print(f"removed {p.name}")
        removed += 1
    print(f"{removed} file(s) removed from {LOOSE}"
          if removed else f"nothing to clean in {LOOSE}")


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd == "1":
        stage1()
    elif cmd == "2":
        stage2()
    elif cmd == "3":
        stage3()
    elif cmd == "clean":
        clean()
    else:
        print(__doc__)


if __name__ == "__main__":
    main()
