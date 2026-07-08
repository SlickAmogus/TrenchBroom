# Research: trenchbroom-extensibility

## Summary

TrenchBroom (local clone at C:/Claude/silenthill/trenchbroom, master v2026.1-139; latest release v2026.1, 2026-06-18) supports fully data-driven custom games: a version-9 GameConfig.cfg + FGD dropped into %APPDATA%\Roaming\TrenchBroom\games\SilentHill\ gives a working SH editor with the stock release binary. The "Quake3 (Valve)" map format is the ideal container: verbatim per-face Valve220 UV axes (exact arbitrary affine UVs), three abusable per-face numbers (surfaceContents/surfaceFlags int + surfaceValue float), and Q3 bezier patches with per-control-point UVs; PNG (via FreeImage, ≤8192px, alpha-aware) covers TIM-converted textures, and Assimp renders TMD-converted .obj/.gltf entity models. The built-in compile dialog (CompilationDialog + QProcess runner with ${MAP_FULL_NAME}-style variables) runs external map2ipd/ipd2map converters with zero fork work. A fork is only required for native TIM loading (~1 file + 1 dispatch branch in lib/TbMdlLib/src/LoadTexture.cpp), native IPD import/export (new parser/serializer in TbMdlLib), or true non-brush mesh display (large: TbMdlLib Node + TbRenderLib + TbUiLib). Fork builds are effectively MSVC-only: VS2022 + Qt 6.10 + vcpkg manifest; MinGW/MSYS2 is unsupported (zero mentions, vcpkg/MSVC-centric CI).

# Adapting TrenchBroom into a Silent Hill 1 Level Editor

Local fork clone: `C:/Claude/silenthill/trenchbroom/` — complete, on `master` at `1b1099ab5` (`git describe` = `v2026.1-139-g1b1099ab5`). NOTE: the codebase was restructured after the old `common/src/` layout; everything now lives in `lib/Tb*Lib/` (TbMdlLib = model/IO, TbUiLib = Qt UI, TbRenderLib = rendering, TbGlLib = GL primitives) and `app/TrenchBroom/`. Latest official release: **v2026.1 (2026-06-18)**; the clone's schema/version facts below were verified identical at tag `v2026.1`.

## 1. Custom game configurations

- **Schema version: 9** — the ONLY accepted version, in master and in release v2026.1 (`lib/TbMdlLib/src/ParseGameConfig.cpp:61` `validVsns = {9}`; verified at tag via `git show v2026.1:lib/TbMdlLib/src/ParseGameConfig.cpp` line 61).
- **User config location (Windows):** `%APPDATA%\TrenchBroom\games\<GameName>\GameConfig.cfg` i.e. `C:\Users\<user>\AppData\Roaming\TrenchBroom\games\SilentHill\GameConfig.cfg`. Evidence: `lib/TbUiLib/src/SystemPaths.cpp:76-99` (`userDataDirectory()` = `QStandardPaths::AppDataLocation`, `userGamesDirectory()` = that + `/games`; header comment `lib/TbUiLib/include/ui/SystemPaths.h:46` says exactly `C:\Users\<user>\AppData\Roaming\TrenchBroom`). Config discovery is recursive on filename `GameConfig.cfg` (`lib/TbMdlLib/src/GameManager.cpp:46`, `:170-173`); user dir is merged with built-in `games/` resource dirs (`lib/TbUiLib/src/AppController.cpp:87-91`).
- **Full key set** (parser: `lib/TbMdlLib/src/ParseGameConfig.cpp:521-567`): `version`, `name`, `icon`, `experimental`, `fileformats[{format, initialmap?}]` (`:509-519`), `filesystem{searchpath, packageformat{extension|extensions, format}}` (`:500-507`), `materials{root, extensions, palette?, attribute?, shaderSearchPath?, excludes?}` (`:484-498`; legacy `format:{extensions:…}` also accepted `:470-482`), `entities{definitions[], defaultcolor, scale?(EL expr), setDefaultProperties?}` (`:444-449`), `tags{brush[], brushface[]}`, `faceattribs{surfaceflags[], contentflags[]}` (names+descriptions for the 32 bit positions; `{"unused": true}` skips bits — see Quake2 example), `softMapBounds`, `compilationTools[{name, description?}]` (`:77-102` — each becomes a `${name}` variable whose value is a per-user tool path preference).
- **Minimal working SilentHill config** (modeled on shipping configs `app/TrenchBroom/resources/games/Generic/GameConfig.cfg` and `Quake2/GameConfig.cfg`):

```json
{
  "version": 9,
  "name": "Silent Hill",
  "fileformats": [ { "format": "Quake3 (Valve)" } ],
  "filesystem": {
    "searchpath": ".",
    "packageformat": { "extension": ".pak", "format": "idpak" }
  },
  "materials": {
    "root": "textures",
    "extensions": [ ".png" ]
  },
  "entities": {
    "definitions": [ "SilentHill.fgd" ],
    "defaultcolor": "0.6 0.6 0.6 1.0"
  },
  "tags": { "brush": [], "brushface": [] },
  "faceattribs": {
    "surfaceflags": [ { "name": "shPolyFlag0", "description": "IPD poly flag bit 0" } ],
    "contentflags": [ { "name": "collidable", "description": "SH collision" } ]
  },
  "compilationTools": [
    { "name": "map2ipd", "description": "Path to map->IPD converter" }
  ]
}
```
Place `SilentHill.fgd` next to it (definitions resolve as `builtin:` relative paths — `lib/TbMdlLib/src/EntityDefinitionFileSpec.cpp:63,88`; `external:` absolute paths also supported). A `packageformat` entry is required by the parser (`ParseGameConfig.cpp:505` uses `at()`, not `atOrDefault`) — point it at a dummy `.pak`. The per-user game path (where `searchpath`/`textures/` live) is set in Preferences at runtime.

## 2. Material / texture support

- **Loader dispatch by extension** (`lib/TbMdlLib/src/LoadTexture.cpp:45-110`): `.d` (Quake mip, needs `materials.palette`), `.c` (HL mip), `.wal` (Quake2, optional palette), `.m8`, `.m32`, `.dds` (`LoadDdsTexture`), else **anything FreeImage supports** — the extension list is built at runtime from every enabled FreeImage plugin (`lib/TbMdlLib/src/LoadFreeImageTexture.cpp:218-241`), so **.png, .tga, .jpg/.jpeg, .bmp, .gif, .psd, .tiff, ... all work**. The game config's `materials.extensions` is the filter used to *find* files (`lib/TbMdlLib/src/LoadMaterialCollections.cpp:87-101`, recursive scan of `materials.root`); `.png` alone is the right choice for SH.
- **Naming/reference from .map faces:** material name = path relative to `materials.root`, extension stripped, forward slashes (`lib/TbMdlLib/src/MaterialUtils.cpp:41-48` `getMaterialNameFromPathSuffix`) — e.g. file `textures/map0_s00/wall01.png` → face material `map0_s00/wall01`. Each subdirectory = one collection in the UI. Names with spaces are quoted on write (`lib/TbMdlLib/src/MapFileSerializer.cpp:85-94`) — avoid spaces anyway.
- **Size limits:** width/height must be 1..8192 (`lib/TbMdlLib/src/MaterialUtils.cpp:81-84` `checkTextureDimensions`). **No power-of-two requirement** (exact-size buffer, 1 mip: `LoadFreeImageTexture.cpp:141-197`).
- **Palette/transparency:** every image is converted to 32-bit RGBA/BGRA (`LoadFreeImageTexture.cpp:159-184`); `FreeImage_IsTransparent()` auto-enables the alpha-mask render path (`:150-151,187`). Palettes are only consumed by legacy formats (.d/.wal). HL-style `{`-prefix names also force masking (`MaterialUtils.cpp:94-97`). For SH: external TIM→PNG conversion should map the PSX STP/black-pixel rule to PNG alpha; 4/8-bit CLUT TIMs depalettize losslessly to PNG.

## 3. Map formats

- **Dialects** (`lib/TbMdlLib/include/mdl/MapFormat.h:29-73`; names accepted in `fileformats`: `lib/TbMdlLib/src/MapFormat.cpp:30-69`): `Standard`, `Valve`, `Quake2`, `Quake2 (Valve)`, `Quake3 (legacy)`, `Quake3 (Valve)`, `Quake3`, `Hexen2`, `Daikatana`. **Quake3 brush primitives are parsed but thrown away** (`lib/TbMdlLib/src/StandardMapParser.cpp:632-659`, TODO 2427 — no face is created) — do not use brushPrimitives.
- **Valve220 exactness:** the two UV axes are read verbatim as arbitrary (non-unit, non-orthogonal) 3-vectors + offsets (`StandardMapParser.cpp:756-770`), stored untouched in `ParallelUVCoordSystem` (`lib/TbMdlLib/src/ParallelUVCoordSystem.cpp:120-125`), and UV is computed as `u = dot(p, uAxis/xScale) + xOffset` (`lib/TbMdlLib/src/UVCoordSystem.cpp:206-212`, `:41-46`), serialized raw (`MapFileSerializer.cpp:114-141`). That is a full affine map R3→R2 per face, so **any per-triangle affine UV assignment is exactly representable** (for a planar polygon whose vertex UVs are affine — always true for a triangle; a non-affine SH quad must be split into 2 triangles). Caveat: it's per-FACE, and TB brushes are closed convex volumes — a lone SH triangle must become a thin prism/tetra brush with 1 "real" face + nodraw faces.
- **Per-face extra attributes to abuse for SH poly metadata:** the Quake2-family formats carry `surfaceContents` (int32), `surfaceFlags` (int32), `surfaceValue` (float) per face — parsed at `StandardMapParser.cpp:505-540` (optional trailing tokens), written when present (`MapFileSerializer.cpp:158-198`). `Daikatana` adds an RGB color triple per face (`StandardMapParser.cpp:585-607`, `MapFileSerializer.cpp:214-238`) but uses paraxial UVs. **`Quake3 (Valve)` is the sweet spot: Valve UV axes + contents/flags/value + bezier patches** (serializer mapping: `MapFileSerializer.cpp:276-301`; `Quake3_Valve` → `Quake2ValveFileSerializer`). `faceattribs` in the game config gives the flag bits editor-visible names.
- **Q3 bezier patches** (`hasPatchSupport`: Quake3/Quake3_Legacy/Quake3_Valve only, `MapFormat.cpp:185-191`): control points are 5-vectors **(x,y,z,u,v) — per-control-point UVs** (`lib/TbMdlLib/include/mdl/BezierPatch.h:46`), `patchDef2` blocks, grid must be odd and ≥3 in both dims (`StandardMapParser.cpp:661-734`). A flat quad as a 3×3 patch with midpoint control points reproduces bilinear UV interpolation exactly — an alternative to thin-prism brushes for display-only geometry, but patches carry NO surface flags.

## 4. Entity definitions

- **FGD fully supported** (`lib/TbMdlLib/src/FgdParser.cpp:309-330`): `@SolidClass` (brush entities), `@PointClass`, `@BaseClass`, `@Main`; also `.def` (`DefParser.cpp`) and `.ent` (`EntParser.cpp`). Referenced from `entities.definitions` in the game config; users can also switch FGDs per-map.
- **Model display:** FGD `model(...)`/`studio(...)`/`sprite(...)` with EL expressions incl. skin/frame/scale (`FgdParser.cpp:400-411`, `:481-499`). Model loading chain (`lib/TbMdlLib/src/LoadEntityModel.cpp:66-121`): native mdl/md2/bsp/spr/md3/mdx/dkm/ase/fm/image-sprite first, then **Assimp** (`lib/TbMdlLib/src/LoadAssimpModel.cpp:882-901`) which accepts `.obj`, `.gltf`, `.glb`, `.fbx`, `.dae`, `.ply`, `.stl`, `.iqm`, `.md5mesh`, etc. **So TMD→.obj (or better .glb, which embeds textures) conversion displays placed SH objects with the stock binary** — put converted models under the game path and reference them from the FGD, e.g. `model({ "path": "models/item_healthdrink.glb" })`. Even a plain `.png` works as a sprite (`LoadImageSpriteModel.cpp:88`).

## 5. What genuinely requires forking

- **Native TIM loading — small.** Add `lib/TbMdlLib/src/LoadTimTexture.cpp` (+header in `include/mdl/`) and one dispatch branch in `lib/TbMdlLib/src/LoadTexture.cpp` (insert before the FreeImage fallback at `:101`); register nothing else — the config's `materials.extensions: [".tim"]` drives discovery. Pattern to copy: `LoadWalTexture.cpp` (palette-based) or `LoadDdsTexture.cpp`. ~200 lines; TIM CLUT→RGBA + STP→alpha.
- **Native IPD import/export — medium.** Import: new parser next to `lib/TbMdlLib/src/StandardMapParser.cpp` feeding `MapReader`/`WorldReader` (`lib/TbMdlLib/src/WorldReader.cpp`, `include/mdl/MapReader.h`); export: new serializer next to `lib/TbMdlLib/src/MapFileSerializer.cpp` / `NodeWriter.cpp` (an OBJ exporter precedent exists: `lib/TbMdlLib/src/ObjSerializer.cpp`, File>Export menu). NOT recommended — external converters via the compile dialog do this with zero fork risk.
- **Arbitrary non-brush mesh geometry — large.** TB has exactly two geometry node types: `BrushNode` and `PatchNode` (see serializer visitor `MapFileSerializer.cpp:315-334`). A triangle-soup node means touching the whole stack: `lib/TbMdlLib` (Node hierarchy, pick/selection, `BrushNode.cpp`/`PatchNode`* as templates), `lib/TbRenderLib` (renderers, `BrushRendererBrushCache.cpp` analog), `lib/TbUiLib` (tools), plus persistence. Avoid: use thin-prism brushes (editable, flag-carrying) + patches/entity-models (display-only) instead.
- **Compile tool integration — NO FORK NEEDED, stock feature.** Run > Compile Map dialog: `lib/TbUiLib/src/CompilationDialog.cpp`, profiles persisted per-game at `%APPDATA%\TrenchBroom\games\<Game>\CompilationProfiles.cfg` (`lib/TbMdlLib/src/GameManager.cpp:47,93`; parser `ParseCompilationConfig.cpp`). Task types (`lib/TbMdlLib/include/mdl/CompilationTask.h:30-81`): **ExportMap** (writes the .map, optional TB-property stripping), CopyFiles, RenameFile, DeleteFiles, **RunTool** (`toolSpec` + `parameterSpec` + treatNonZeroResultCodeAsError), executed via `QProcess` with live output panel (`lib/TbUiLib/src/CompilationRunner.cpp:331-368`). Variables interpolated in all specs (`lib/TbUiLib/src/CompilationVariables.cpp:40-95`): `${MAP_BASE_NAME}`, `${MAP_FULL_NAME}`, `${MAP_DIR_PATH}`, `${GAME_DIR_PATH}`, `${APP_DIR_PATH}`, `${WORK_DIR_PATH}`, `${CPU_COUNT}`, `${MODS}`, plus one `${<name>}` per `compilationTools` entry (user-set exe path). Same variable system powers Run > Launch Engine (`LaunchGameEngineDialog.cpp`, `GameEngineProfiles.cfg` — can launch the SH PC port pointing at the rebuilt map DLL).

## 6. Windows build requirements (for the eventual fork)

- **Qt 6.10 exactly-or-later** (BUILD.md: "earlier versions will definitely not work"); modules: Widgets, OpenGL, OpenGLWidgets, Svg, Network (`lib/TbUiLib/CMakeLists.txt:487-493`).
- **vcpkg manifest** `vcpkg.json` (auto-bootstrapped at CMake configure): assimp ≥5.3.1, catch2 ≥3.10, cpptrace, ctre, fmt ≥11.2, freeimage ≥3.18, freetype, miniz, stduuid, tinyxml2, rapidjson override; builtin-baseline pinned.
- **Compiler: effectively MSVC-only on Windows.** Documented path: VS2022, toolset v143, `cmake .. -G"Visual Studio 17 2022" -T v143 -A x64 -DCMAKE_PREFIX_PATH=<QT>\msvc2022_64` (BUILD.md); CI uses `vcvarsall.bat x64` + Ninja (`CI-windows.bat`). C++20 with heavy std::ranges (GCC≥13 required on Linux). **Zero mentions of MinGW/MSYS2 anywhere** (grep over BUILD.md/CMakeLists/cmake/) — vcpkg deps (freeimage, assimp) and Qt msvc2022_64 binding make MSYS2 impractical; do not attempt. Also needs CMake + pandoc. Note: this is a DIFFERENT toolchain from the SH port's MSYS2 build — the fork build cannot share it.
- **Prebuilt Windows release (use for all v1 work):** https://github.com/TrenchBroom/TrenchBroom/releases/download/v2026.1/TrenchBroom-Win64-AMD64-v2026.1-Release.zip (v2026.1, 2026-06-18; portable zip — with a `config/` dir next to the exe it runs portable, `SystemPaths.cpp:78-85`).

## Decision table: v1 (stock binary) vs v2 (fork)

| Capability | v1 — stock v2026.1 binary + data | v2 — fork (concrete pointers) |
|---|---|---|
| Game definition | `GameConfig.cfg` v9 + `SilentHill.fgd` in `%APPDATA%\TrenchBroom\games\SilentHill\` | Ship as built-in: `app/TrenchBroom/resources/games/SilentHill/` |
| Map container | `Quake3 (Valve)` format: exact affine UVs + 2×int32 + 1×float per face + patches | Native `.ipd` open/save: parser beside `StandardMapParser.cpp`, serializer beside `MapFileSerializer.cpp` |
| Textures | External `tim2png.py` (CLUT→RGBA, STP→alpha) into `<gamepath>/textures/<sheet>/…png`; ≤8192px, non-pow2 OK | `LoadTimTexture.cpp` + branch in `lib/TbMdlLib/src/LoadTexture.cpp:101`; config lists `.tim` |
| Geometry IPD→editor | External `ipd2map` converter: 1 thin-prism brush per tri/quad (Valve axes solved from the 3 UV pairs), SH flags → surfaceContents/Flags/Value; display-only clutter optionally as 3×3 patches | Triangle-soup Node type: `lib/TbMdlLib` (Node/pick), `lib/TbRenderLib` (renderer), `lib/TbUiLib` (tools) — the big-ticket item, defer |
| Geometry editor→game | `map2ipd` converter run by stock compile dialog (RunTool + `${MAP_FULL_NAME}` etc.), then rebuild the map DLL via existing msys2 pipeline; profiles in `CompilationProfiles.cfg` | Same converters, or native export via new serializer; optionally custom compile-task types in `CompilationTask.h`/`CompilationRunner.cpp` |
| Placed objects (TMD) | `tmd2glb`/`tmd2obj` converter; FGD `model({"path": "models/x.glb"})` rendered by Assimp | Native TMD loader beside `LoadAssimpModel.cpp`, registered in `LoadEntityModel.cpp:66-121` |
| SH entity/event data | FGD point/solid classes with key/values; unknown keys are preserved in the .map roundtrip | Same; optionally smart editors in TbUiLib |
| Playtesting | Run > Launch Engine → SH PC port exe (`GameEngineProfiles.cfg`) | Same |

**Recommended path:** all v1 items work today with the release zip; the entire SH-specific effort is three external converters (tim2png, ipd2map/map2ipd, tmd2glb) + one GameConfig.cfg + one FGD. Fork only when (a) TIM count/iteration makes pre-conversion annoying, or (b) thin-prism-brush editing UX proves inadequate and a real mesh node is justified.

## Key files

- C:/Claude/silenthill/trenchbroom/lib/TbMdlLib/src/ParseGameConfig.cpp — GameConfig.cfg schema authority: version 9 check (line 61), all keys (521-567), materials (484-498), compilationTools (77-102)
- C:/Claude/silenthill/trenchbroom/app/TrenchBroom/resources/games/Quake2/GameConfig.cfg — Best template: faceattribs surfaceflags/contentflags, tags, compilationTools; Generic/GameConfig.cfg is the minimal template
- C:/Claude/silenthill/trenchbroom/lib/TbUiLib/src/SystemPaths.cpp — User config paths: userDataDirectory (76-94) = %APPDATA%\TrenchBroom, userGamesDirectory (96-99) = +\games
- C:/Claude/silenthill/trenchbroom/lib/TbMdlLib/src/LoadTexture.cpp — Texture loader dispatch by extension (45-110) — the single insertion point for a native TIM loader (before FreeImage fallback at 101)
- C:/Claude/silenthill/trenchbroom/lib/TbMdlLib/src/StandardMapParser.cpp — .map parsing: Valve UV axes verbatim (756-770), Quake2-family surface contents/flags/value (505-540), patchDef2 with 5D control points (661-734), brush primitives discarded (632-659)
- C:/Claude/silenthill/trenchbroom/lib/TbMdlLib/src/MapFileSerializer.cpp — .map writing: Valve axes raw (114-141), surface attribs (158-198), format→serializer map (276-301); Quake3_Valve = Valve UV + flags
- C:/Claude/silenthill/trenchbroom/lib/TbMdlLib/src/LoadEntityModel.cpp — Entity model loader chain ending in Assimp (66-121); LoadAssimpModel.cpp:882-901 lists .obj/.gltf/.glb/.fbx support for TMD-converted models
- C:/Claude/silenthill/trenchbroom/lib/TbUiLib/src/CompilationRunner.cpp — Stock external-tool compile pipeline (QProcess at 331-368); variables in CompilationVariables.cpp:40-95; task types in TbMdlLib/include/mdl/CompilationTask.h
- C:/Claude/silenthill/trenchbroom/BUILD.md — Fork build requirements: Qt 6.10, VS2022/MSVC v143, vcpkg manifest (vcpkg.json), CMake+pandoc; no MinGW support
- C:/Claude/silenthill/trenchbroom/lib/TbMdlLib/src/GameManager.cpp — Config discovery (GameConfig.cfg recursive, line 46,170-173) and per-game CompilationProfiles.cfg/GameEngineProfiles.cfg locations (47-48, 93, 112)

## Open questions

- SH coordinate/unit mapping: PSX fixed-point world units vs TB units (grid snapping default powers of 2) — converter must pick a scale factor; also PSX +Y-down vs TB +Z-up axis swap needs a convention before writing ipd2map.
- IPD poly metadata width: if SH per-poly data exceeds 2x int32 + 1 float (surfaceContents/surfaceFlags/surfaceValue), the overflow must go into brush-entity keys or a sidecar file keyed by poly id — needs an IPD field census first.
- Whether TB's float→text roundtrip of Valve UV axes is bit-exact enough for byte-identical IPD regeneration, or whether map2ipd should re-quantize UVs to the PSX 8-bit texel grid (probably the latter, making exactness moot).
- TIM→PNG semi-transparency: PSX STP bit encodes blend modes (not plain alpha); v1 converter must choose an approximation for editor display (game rendering unaffected since IPD keeps original TIM references).
- The vcpkg-overlay-ports/ dir in the clone was not inspected — if a fork is pursued, check for patched ports (freeimage/assimp) that affect Windows build reproducibility.
