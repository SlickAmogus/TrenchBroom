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

BG = Path(r"C:\Claude\silenthill\disc_extract\BG")
LOOSE = Path(r"C:\Claude\silenthill\silent-hill-decomp\pc_port\build\gamedata\load\BG")
FILES = ["DRU0000.IPD", "DRU01F.TIM"]


def stage1():
    LOOSE.mkdir(parents=True, exist_ok=True)
    shutil.copy2(BG / "DRU0000.IPD", LOOSE / "DRU0000.IPD")
    print(f"stage 1: unmodified DRU0000.IPD -> {LOOSE}")
    print("expect: sewer entrance area renders EXACTLY as normal.")
    print("check SilentHill.log for the loose-file hit line (SH_LOOSE_VERBOSE=1).")


def stage2():
    LOOSE.mkdir(parents=True, exist_ok=True)
    from PIL import Image
    tim_raw = (BG / "DRU01F.TIM").read_bytes()
    tim = Tim.parse(tim_raw)
    rgba, _ = tim.rgba_for_clut_row(0)
    img = Image.frombytes("RGBA", (tim.width, tim.height), rgba)
    for y in range(32, 96):
        for x in range(32, 96):
            img.putpixel((x, y), (248, 0, 0, 255))
    tmp = LOOSE / "_dru01f_red.png"
    img.save(tmp)
    import subprocess
    subprocess.run([sys.executable, str(Path(__file__).parent / "png2tim.py"),
                    "--png", str(tmp), "--tim", str(BG / "DRU01F.TIM"),
                    "-o", str(LOOSE / "DRU01F.TIM")], check=True)
    tmp.unlink()
    print("stage 2: DRU01F.TIM with red square -> expect red patch on sewer walls.")


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
    for f in FILES:
        p = LOOSE / f
        if p.exists():
            p.unlink()
            print(f"removed {p}")


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
