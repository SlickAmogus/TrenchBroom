"""First-run setup: find (or ask for) the three paths every tool needs, check
them, and save sh1paths.json.

  python setup_paths.py            # interactive, with auto-detected defaults
  python setup_paths.py --show     # print what the tools currently resolve
  python setup_paths.py --disc D:\\sh1\\disc_extract --port D:\\games\\SilentHillPC
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from sh1fmt import paths


def ask(label, current, validate, hint):
    while True:
        shown = f" [{current}]" if current else ""
        try:
            answer = input(f"{label}{shown}: ").strip().strip('"')
        except EOFError:
            answer = ""
        value = Path(answer) if answer else (Path(current) if current else None)
        if value is None:
            print(f"  needed. {hint}")
            continue
        ok, why = validate(value)
        if ok:
            return value
        print(f"  {why}")
        print(f"  {hint}")
        current = None


def check_disc(p):
    if not p.is_dir():
        return False, f"{p} is not a directory"
    if not (p / "BG").is_dir():
        return False, f"{p} has no BG/ subdirectory"
    n = len(list((p / "BG").glob("*.IPD")))
    if n == 0:
        return False, f"{p / 'BG'} contains no .IPD files"
    return True, f"{n} IPD cells"


def check_port(p):
    if not p.is_dir():
        return False, f"{p} is not a directory"
    if not (p / "SilentHillPC.exe").is_file():
        return False, f"no SilentHillPC.exe in {p}"
    return True, "ok"


def check_gamedir(p):
    try:
        p.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        return False, f"cannot create {p}: {e}"
    return True, "ok"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--show", action="store_true")
    ap.add_argument("--disc")
    ap.add_argument("--gamedir")
    ap.add_argument("--port")
    args = ap.parse_args()

    if args.show:
        print(paths.describe())
        return 0

    cfg, existing = paths.load_config()
    non_interactive = any((args.disc, args.gamedir, args.port))

    def resolve(flag, cfg_key, autodetect, label, validate, hint):
        if flag:
            v = Path(flag)
        elif non_interactive:
            v = Path(cfg.get(cfg_key)) if cfg.get(cfg_key) else autodetect()
        else:
            guess = cfg.get(cfg_key) or autodetect()
            v = ask(label, str(guess) if guess else "", validate, hint)
        if v is None:
            print(f"  {label}: not set")
            return None
        ok, why = validate(v)
        print(f"  {'OK  ' if ok else 'BAD '} {label}: {v}  ({why})")
        return v if ok else None

    print("Silent Hill level editor - path setup\n")
    disc = resolve(args.disc, "disc", lambda: paths.disc_dir(required=False),
                   "Extracted disc assets (folder containing BG/)", check_disc,
                   "Extract with silent-hill-decomp/tools/silentassets/extract.py")
    gdir = resolve(args.gamedir, "gamedir", paths.gamedir,
                   "Editor game dir (converted maps + textures go here)",
                   check_gamedir, "Any writable folder; it will be created.")
    port = resolve(args.port, "port", lambda: paths.port_dir(required=False),
                   "PC port build dir (folder holding SilentHillPC.exe)",
                   check_port, "Optional - only needed to compile into the game.")

    new = dict(cfg)
    if disc:
        new["disc"] = str(disc)
    if gdir:
        new["gamedir"] = str(gdir)
    if port:
        new["port"] = str(port)
    where = paths.save_config(new, existing)
    print(f"\nsaved {where}")

    if port:
        cfgfile = port / "config.cfg"
        if cfgfile.is_file():
            text = cfgfile.read_text(encoding="utf-8", errors="replace")
            if "allow_loose_files = 1" not in text:
                print(f"\nNOTE: set 'allow_loose_files = 1' in {cfgfile} "
                      f"or the game will ignore everything you compile.")
    if not disc:
        print("\nDisc assets are required - convert/compile will not run without them.")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
