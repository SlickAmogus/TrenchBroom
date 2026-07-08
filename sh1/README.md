# Silent Hill 1 Level Editor (TrenchBroom-based)

Edit real Silent Hill 1 (PSX) map geometry and textures in TrenchBroom and load
the result in the silent-hill-decomp PC port — no disc rebuild required.

Design + format research: see `../docs/DESIGN.md` and `../docs/research/`.

## Requirements

- Stock TrenchBroom v2026.1 Windows release (no fork build needed for v1):
  `C:\Claude\silenthill\trenchbroom-release\TrenchBroom.exe`
- Python 3 + Pillow
- Extracted disc assets at `C:\Claude\silenthill\disc_extract\BG\`

## Quick start

```bat
cd sh1\tools

:: 1. one-time: install the Silent Hill game config into TrenchBroom
python install_gameconfig.py

:: 2. convert an area (all its IPD cells + textures) into an editable map
python ipd2map.py --area DRU          & :: otherworld sewer, smallest area

:: 3. edit in TrenchBroom
"C:\Claude\silenthill\trenchbroom-release\TrenchBroom.exe" C:\Claude\silenthill\sh1editor\maps\DRU.map

:: 4. compile edits back into IPD files the game will load
python map2ipd.py --map C:\Claude\silenthill\sh1editor\maps\DRU.map

:: 5. test in the PC port: set allow_loose_files=1 in config.cfg, launch, and
::    enter the area (map6_s03 for DRU). The port loads the edited cells from
::    gamedata/load/BG/ instead of the disc image.
```

Area tags → map DLLs (full table in docs/research/disc-inventory.md):
THR = town streets, SC/SU = school, HP/HU = hospital, ER = misc interiors
(shared by 11 maps!), SPR/SPU = commercial, RSR/RSU = resort, DR/DRU = sewers,
APU = amusement park.

## What v1 supports

- Full textured view/editing of real map geometry (one thin-prism brush per
  SH tri/quad; exact PSX UVs; one TrenchBroom group per IPD cell).
- **Retexture**: apply any material already in the cell's material list
  (`bg/<TIM>_r<row>`), UV realignment, PSX semi-transparency flag.
- **Vertex moves** on single-instance models (most terrain). Moving a vertex
  shared by neighbouring faces stretches them, like any mesh editor.
- Compile is an in-place patch: output IPD size == original ⇒ always fits the
  loose-file override and the game's chunk buffers.
- Byte-exact round-trip: compiling an unedited map produces zero changes.

## v1 limits (see DESIGN.md roadmap)

- No new/deleted brushes, no new textures in a cell, no collision editing yet
  (collision block passes through untouched — moved walls keep old collision!).
- Faces on multi-instance models / the shared `<TAG>_GLB.PLM` refuse edits
  unless `--allow-plm` (PLM edits affect every map using the area).
- Entities (spawns, triggers, cameras) live in the map DLLs, not IPDs — v2.

## Face metadata contract

`surfaceValue` = face ID into `<AREA>.manifest.json` (provenance: cell,
container, model, mesh, prim, corners). `surfaceFlags`: bit0 = PSX
semi-transparent (additive), bit1 = second half of a split quad, bit2 = global
PLM model. New faces drawn in TrenchBroom have no ID (0) and are ignored by the
v1 compiler.
