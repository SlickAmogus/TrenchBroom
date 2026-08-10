# Where everything lives

## The editor

| What | Where |
|---|---|
| Fork repo (all editor work) | `C:\Claude\silenthill\trenchbroom`, branch `sh1-editor` |
| **Our custom TrenchBroom build** | `trenchbroom\build\app\TrenchBroom\Release\TrenchBroom.exe` |
| Stock TrenchBroom (fallback) | `C:\Claude\silenthill\trenchbroom-release\TrenchBroom.exe` |
| C++ changes we made to TrenchBroom | `lib/TbMdlLib/src/LoadTimTexture.cpp` (+ header, one dispatch line in `LoadTexture.cpp`, 2 CMakeLists lines) |
| Python tools | `trenchbroom\sh1\tools\` |
| Game config + FGD (source) | `trenchbroom\sh1\games\SilentHill\` |
| Game config (installed, what TB reads) | `%APPDATA%\TrenchBroom\games\SilentHill\` |
| Path config | `trenchbroom\sh1\sh1paths.json` |

## The data

| What | Where |
|---|---|
| Extracted disc assets (input) | `C:\Claude\silenthill\disc_extract\BG\` |
| Converted maps + textures (working dir) | `C:\Claude\silenthill\sh1editor\` — `maps\<AREA>.map`, `textures\bg\*.png` |
| Compiled output the game reads | `silent-hill-decomp\pc_port\build\gamedata\load\BG\` |

All three are configurable — see `sh1paths.json` / `python setup_paths.py --show`.

## If you ever hand this to someone else

Ship: the TrenchBroom build, `sh1/tools/`, `sh1/games/`, the docs. They run
`setup_paths.py` then `install_gameconfig.py`.

Never ship: anything from `disc_extract/`, or converted maps/textures — that's
Konami's data. Users extract from their own disc with the decomp's
`tools/silentassets/extract.py`.

TrenchBroom is GPLv3, so a public binary must link to the fork source it was
built from.
