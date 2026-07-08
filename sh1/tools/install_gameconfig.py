"""Install the Silent Hill game config into TrenchBroom's user games directory
and point the game-path preference at the generated game data directory.

Usage: python install_gameconfig.py [--gamedir C:/Claude/silenthill/sh1editor]
"""

import argparse
import json
import os
import shutil
from pathlib import Path

GAMES_SRC = Path(__file__).parent.parent / "games" / "SilentHill"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--gamedir", default=r"C:\Claude\silenthill\sh1editor")
    args = ap.parse_args()

    appdata = Path(os.environ["APPDATA"]) / "TrenchBroom"
    dest = appdata / "games" / "SilentHill"
    dest.mkdir(parents=True, exist_ok=True)
    for f in GAMES_SRC.iterdir():
        shutil.copy2(f, dest / f.name)
        print(f"installed {dest / f.name}")

    prefs_path = appdata / "Preferences.json"
    prefs = {}
    if prefs_path.exists():
        prefs = json.loads(prefs_path.read_text(encoding="utf-8"))
    prefs["Games/Silent Hill/Path"] = str(Path(args.gamedir)).replace("\\", "/")
    prefs_path.write_text(json.dumps(prefs, indent=2), encoding="utf-8")
    print(f"set Games/Silent Hill/Path = {prefs['Games/Silent Hill/Path']}")


if __name__ == "__main__":
    main()
