"""Install the Silent Hill game config into TrenchBroom's user games directory,
point the game-path preference at the generated game data directory, and seed
the Run > Compile Map and Run > Launch Engine profiles.

Usage: python install_gameconfig.py [--gamedir C:/Claude/silenthill/sh1editor]
           [--engine <path to SilentHillPC.exe>] [--no-profiles]

Re-run this any time; it is idempotent. If TrenchBroom overwrote the compile
profiles from its UI, re-running restores them.
"""

import argparse
import json
import os
import shutil
import sys
from pathlib import Path

GAMES_SRC = Path(__file__).parent.parent / "games" / "SilentHill"
TOOLS_DIR = Path(__file__).parent.resolve()

sys.path.insert(0, str(TOOLS_DIR))
from sh1fmt import paths


def default_engine():
    port = paths.port_dir(required=False)
    return str(port / "SilentHillPC.exe") if port else ""


def compilation_profiles():
    python = Path(sys.executable).as_posix()
    map2ipd = (TOOLS_DIR / "map2ipd.py").as_posix()
    return {
        "version": 1,
        "profiles": [
            {
                "name": "Compile to game (loose files)",
                "workdir": "${MAP_DIR_PATH}",
                "tasks": [
                    {
                        "type": "export",
                        "target": "${WORK_DIR_PATH}/${MAP_BASE_NAME}-compile.map",
                    },
                    {
                        "type": "tool",
                        "tool": python,
                        "parameters": (
                            f"{map2ipd} "
                            "--map ${WORK_DIR_PATH}/${MAP_BASE_NAME}-compile.map "
                            "--manifest ${MAP_DIR_PATH}/${MAP_BASE_NAME}.manifest.json"
                        ),
                        "treatNonZeroResultCodeAsError": True,
                    },
                ],
            }
        ],
    }


def engine_profiles(engine_path):
    return {
        "version": 1,
        "profiles": [
            {
                "name": "Silent Hill PC Port",
                "path": Path(engine_path).as_posix(),
                "parameters": "",
            }
        ],
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--gamedir", default=None)
    ap.add_argument("--engine", default=None)
    ap.add_argument("--no-profiles", action="store_true")
    args = ap.parse_args()
    if args.gamedir is None:
        args.gamedir = str(paths.gamedir())
    if args.engine is None:
        args.engine = default_engine()

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

    if not args.no_profiles:
        cp = dest / "CompilationProfiles.cfg"
        cp.write_text(json.dumps(compilation_profiles(), indent=4), encoding="utf-8")
        print(f"installed {cp} (Run > Compile Map)")
        if Path(args.engine).exists():
            ep = dest / "GameEngineProfiles.cfg"
            ep.write_text(json.dumps(engine_profiles(args.engine), indent=4),
                          encoding="utf-8")
            print(f"installed {ep} (Run > Launch Engine -> {args.engine})")
        else:
            print(f"engine not found at {args.engine}; skipped GameEngineProfiles.cfg")


if __name__ == "__main__":
    main()
