"""Push edited texture PNGs into the game as hi-res overrides.

The PC port accepts per-CLUT-row PNG/DDS overrides named
`gamedata/load/BG/<SHEET>.TIM.p<NN>.png` (fsqueue_3.c: Loose_HasPerRow). Those
are NOT palette-limited and NOT size-limited: repaint an exported sheet at any
resolution, in full colour, and drop it in.

That makes this the preferred texture path. `png2tim.py` remains the only way
to produce a real TIM (needed when something must stay a genuine 4bpp disc
file), but for looking different in game, use this.

  python textures_to_game.py --area DRU        # push every edited DRU sheet
  python textures_to_game.py --sheet DRU01F    # push one sheet's rows
  python textures_to_game.py --area DRU --dry-run
  python textures_to_game.py --clean --area DRU

"Edited" means the PNG differs from a fresh export of the disc TIM, so pushing
an untouched texture folder copies nothing.
"""

import argparse
import re
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from sh1fmt import Tim, paths

NAME_RE = re.compile(r"^([A-Z0-9_]+)_r(\d+)\.png$", re.IGNORECASE)


def exported_matches_disc(png_path, tim_path, row):
    """True when the PNG is still exactly what ipd2map exported (unedited)."""
    try:
        from PIL import Image
        img = Image.open(png_path).convert("RGBA")
        tim = Tim.parse(tim_path.read_bytes())
        if img.size != (tim.width, tim.height):
            return False          # resized => definitely edited
        rgba, _ = tim.rgba_for_clut_row(row)
        return img.tobytes() == rgba
    except Exception:
        return False


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--area", help="only sheets whose name starts with this tag")
    ap.add_argument("--sheet", help="a single TIM base name, e.g. DRU01F")
    ap.add_argument("--gamedir", default=None)
    ap.add_argument("--disc", default=None)
    ap.add_argument("--out", default=None, help="default <port>/gamedata/load/BG")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--clean", action="store_true",
                    help="remove pushed overrides instead of writing them")
    ap.add_argument("--force", action="store_true",
                    help="push even sheets identical to the disc original")
    args = ap.parse_args()

    tex = Path(paths.gamedir(args.gamedir)) / "textures" / "bg"
    bg = paths.bg_dir(args.disc)
    out = Path(args.out) if args.out else paths.loose_bg_dir()
    if not tex.is_dir():
        sys.exit(f"no exported textures at {tex} - run ipd2map first")

    selected = []
    for png in sorted(tex.glob("*.png")):
        m = NAME_RE.match(png.name)
        if not m:
            continue
        sheet, row = m.group(1).upper(), int(m.group(2))
        if args.sheet and sheet != args.sheet.upper():
            continue
        if args.area and not sheet.startswith(args.area.upper()):
            continue
        selected.append((png, sheet, row))

    if not selected:
        sys.exit("nothing selected (check --area / --sheet)")

    pushed = skipped = removed = 0
    for png, sheet, row in selected:
        dest = out / f"{sheet}.TIM.p{row:02d}.png"
        if args.clean:
            if dest.exists() and not args.dry_run:
                dest.unlink()
            if dest.exists() or args.dry_run:
                print(f"remove {dest.name}")
            removed += 1
            continue
        tim = bg / f"{sheet}.TIM"
        if not args.force and tim.is_file() and exported_matches_disc(png, tim, row):
            skipped += 1
            continue
        print(f"push {png.name} -> {dest.name}")
        if not args.dry_run:
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(png, dest)
        pushed += 1

    if args.clean:
        print(f"\n{removed} override(s) {'would be ' if args.dry_run else ''}removed "
              f"from {out}")
    else:
        print(f"\n{pushed} sheet(s) {'would be ' if args.dry_run else ''}pushed to {out}"
              f"; {skipped} unchanged (use --force to push anyway)")
        if pushed:
            print("A per-row set must include row 0 for the port to use it: if a "
                  "sheet shows no change in game, export/push its .p00 row too.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
