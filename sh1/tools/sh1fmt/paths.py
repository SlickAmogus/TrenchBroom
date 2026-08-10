"""Where everything lives, resolved instead of hardcoded.

Resolution order for every path (first hit wins):
  1. explicit --disc / --gamedir / --out on the command line
  2. environment: SH1_DISC, SH1_GAMEDIR, SH1_PORT
  3. sh1paths.json  (next to sh1/, or %APPDATA%/SilentHillEditor/)
  4. auto-detection: walk up from this file looking for the known layout
  5. give up and say what to set, rather than failing with a stale path

Written so the tools work unchanged on the dev machine (auto-detection finds
the usual layout) and on a user's machine after `python setup_paths.py`.
"""

import json
import os
from pathlib import Path

CONFIG_NAME = "sh1paths.json"
# sh1/tools/sh1fmt/paths.py -> sh1/tools -> sh1 -> <repo>
SH1_DIR = Path(__file__).resolve().parent.parent.parent
REPO_DIR = SH1_DIR.parent


def _config_locations():
    yield SH1_DIR / CONFIG_NAME
    appdata = os.environ.get("APPDATA")
    if appdata:
        yield Path(appdata) / "SilentHillEditor" / CONFIG_NAME


def load_config():
    for p in _config_locations():
        if p.is_file():
            try:
                return json.loads(p.read_text(encoding="utf-8")), p
            except (OSError, ValueError):
                continue
    return {}, None


def save_config(cfg, path=None):
    path = Path(path) if path else SH1_DIR / CONFIG_NAME
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
    return path


def _search_roots():
    """Directories worth probing: the repo and its neighbours, then ancestors."""
    seen = []
    for base in (REPO_DIR, REPO_DIR.parent, Path.cwd()):
        for cand in (base, *base.parents):
            if cand not in seen:
                seen.append(cand)
            if len(seen) > 24:
                break
    return seen


def _autodetect_disc():
    """A directory holding BG/*.IPD — the extracted disc assets."""
    for root in _search_roots():
        for name in ("disc_extract", "disc", "assets", "gamedata"):
            cand = root / name
            if (cand / "BG").is_dir() and any((cand / "BG").glob("*.IPD")):
                return cand
    return None


def _autodetect_port():
    """The PC port build directory (holds SilentHillPC.exe or config.cfg)."""
    for root in _search_roots():
        for rel in ("silent-hill-decomp/pc_port/build", "pc_port/build",
                    "SilentHillPC", "build"):
            cand = root / rel
            if (cand / "SilentHillPC.exe").is_file():
                return cand
    return None


def _resolve(explicit, env_var, cfg_key, autodetect, label, required):
    if explicit:
        return Path(explicit)
    env = os.environ.get(env_var)
    if env:
        return Path(env)
    cfg, _ = load_config()
    if cfg.get(cfg_key):
        return Path(cfg[cfg_key])
    found = autodetect()
    if found:
        return found
    if required:
        raise SystemExit(
            f"cannot find {label}.\n"
            f"  Fix with any one of:\n"
            f"    python setup_paths.py            (interactive, saves {CONFIG_NAME})\n"
            f"    set {env_var}=<path>\n"
            f"    pass the command-line option explicitly")
    return None


def disc_dir(explicit=None, required=True):
    """Extracted disc assets root (the dir containing BG/)."""
    return _resolve(explicit, "SH1_DISC", "disc", _autodetect_disc,
                    "the extracted disc assets (a folder containing BG/*.IPD)",
                    required)


def bg_dir(explicit=None, required=True):
    d = disc_dir(explicit, required)
    return d / "BG" if d else None


def gamedir(explicit=None):
    """Where converted maps + textures live (the TrenchBroom 'game path')."""
    if explicit:
        return Path(explicit)
    env = os.environ.get("SH1_GAMEDIR")
    if env:
        return Path(env)
    cfg, _ = load_config()
    if cfg.get("gamedir"):
        return Path(cfg["gamedir"])
    return REPO_DIR / "sh1editor"


def port_dir(explicit=None, required=False):
    """The PC port build directory."""
    return _resolve(explicit, "SH1_PORT", "port", _autodetect_port,
                    "the Silent Hill PC port build directory "
                    "(the folder holding SilentHillPC.exe)", required)


def loose_bg_dir(explicit=None):
    """Where compiled files go: <port>/gamedata/load/BG."""
    if explicit:
        return Path(explicit)
    p = port_dir(required=False)
    if p is None:
        raise SystemExit(
            "cannot find the PC port build directory, so there is nowhere to "
            "write compiled files.\n"
            "  Fix with: python setup_paths.py, set SH1_PORT=<path>, or pass --out")
    return p / "gamedata" / "load" / "BG"


def describe():
    cfg, src = load_config()
    lines = [f"config file : {src if src else '(none - using auto-detection)'}"]
    for label, fn in (("disc assets", lambda: disc_dir(required=False)),
                      ("game dir   ", gamedir),
                      ("port build ", lambda: port_dir(required=False))):
        try:
            v = fn()
        except SystemExit:
            v = None
        lines.append(f"{label} : {v if v else '(not found)'}")
    return "\n".join(lines)
