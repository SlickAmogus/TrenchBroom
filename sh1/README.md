# Silent Hill 1 Level Editor (TrenchBroom-based)

Edit real Silent Hill 1 (PSX) map geometry and textures in TrenchBroom and load
the result in the silent-hill-decomp PC port — no disc rebuild required.

- Design + decisions: `../docs/DESIGN.md`
- Byte-level format research: `../docs/research/`
- Engine-side roadmap (size caps, new cells, custom assets): `../docs/PC_PORT_INTEGRATION.md`

## Requirements

- TrenchBroom v2026.1+ — either the stock release
  (`C:\Claude\silenthill\trenchbroom-release\TrenchBroom.exe`) or this fork's
  build (adds native `.TIM` loading)
- Python 3 + Pillow
- Extracted disc assets at `C:\Claude\silenthill\disc_extract\BG\`

## One-time setup

```bat
cd sh1\tools
python install_gameconfig.py
```

This installs into `%APPDATA%\TrenchBroom\games\SilentHill\`:
the game config + FGD, a **Run > Compile Map** profile that runs `map2ipd`,
and a **Run > Launch Engine** profile pointing at `SilentHillPC.exe`.
It also sets the game path preference to `C:\Claude\silenthill\sh1editor`
(where converted maps and textures live). Re-run any time — it's idempotent,
and restores the profiles if TrenchBroom's UI overwrote them.

## Which map do I edit? (area tags vs map DLLs)

Level geometry belongs to an **area tag**, not to a map DLL — several map DLLs
render the same area. Editing an area affects every map DLL that uses it:

| Area | .map file | Locale | Used by map DLLs |
|------|-----------|--------|------------------|
| THR | THR.map | town streets | map0_s00, map0_s01, map2_s00, map2_s03 |
| SC  | SC.map  | school (normal) | map1_s00, map1_s01, map1_s06 |
| SU  | SU.map  | school (otherworld) | map1_s02–s05 |
| ER  | ER.map  | misc interiors: cafe, church, motel, boat, Nowhere | **11 DLLs**: map0_s02, map2_s01, map2_s04, map4_s01, map5_s02, map5_s03, map6_s01, map7_s00–s03 |
| HP  | HP.map  | hospital (fog) | map3_s00, map3_s01, map3_s06 |
| HU  | HU.map  | hospital (otherworld) | map3_s02–s05, map4_s04 |
| SPR | SPR.map | commercial district (normal) | map2_s02, map4_s00, map4_s06 |
| SPU | SPU.map | commercial district (otherworld) | map4_s02, map4_s03, map4_s05 |
| RSR | RSR.map | lakeside resort | map5_s01 |
| RSU | RSU.map | resort (otherworld) | map6_s00, map6_s02 |
| DR  | DR.map  | sewers | map5_s00 |
| DRU | DRU.map | sewers (otherworld) — smallest area, best test target | map6_s03 |
| APU | APU.map | amusement park (otherworld) | map6_s04, map6_s05 |

Inside a .map, each IPD cell is a TrenchBroom **group** named after its file
(e.g. `DRU0000`) — use the Map view's group list to isolate one cell.

## The edit loop

```bat
:: 1. convert an area (writes <gamedir>\maps\<AREA>.map + textures + manifest)
python ipd2map.py --area DRU

:: 2. open in TrenchBroom (or File > Open; all converted areas are available)
TrenchBroom.exe C:\Claude\silenthill\sh1editor\maps\DRU.map

:: 3. edit: retexture faces (material browser, bg/ collection), realign UVs,
::    move vertices/brushes. Face attribute "value" is the round-trip ID -
::    don't change it by hand.

:: 4. compile: Run > Compile Map > "Compile to game (loose files)"
::    (or manually: python map2ipd.py --map ...\maps\DRU.map)
::    -> writes changed cells to pc_port\build\gamedata\load\BG\

:: 5. test: Run > Launch Engine (or start SilentHillPC.exe yourself) with
::    allow_loose_files = 1 in config.cfg, then enter the area in-game.
```

`map2ipd` only writes cells that actually changed, patches them in place
(output size == original, always loose-file safe), and prints exactly what it
did. Compiling an unedited map writes nothing — the pipeline is byte-exact in
both directions.

**IMPORTANT — the loose-file loader has never been tested in game.** Before
trusting the loop, run the staged smoke test and check each stage in the
otherworld sewer (map6_s03):

```bat
python loose_smoke_test.py 1   :: unmodified IPD copy -> must look normal
python loose_smoke_test.py 2   :: red square on a wall texture
python loose_smoke_test.py 3   :: retextured + raised water tile
python loose_smoke_test.py clean
```

The loose path is CWD-relative: launch the game from its own build directory.
Set `SH_LOOSE_VERBOSE=1` to log every loose-file probe to SilentHill.log.

## Custom textures

Two independent paths:

1. **Repaint an existing sheet** (works today, no editor involved):
   edit the exported PNG (`sh1editor\textures\bg\<TIM>_r<row>.png`), then
   `python png2tim.py --png edited.png --tim disc_extract\BG\<TIM>.TIM --row <row>`
   → writes a loose TIM. Packing is identity-preserving: untouched pixels keep
   their exact bytes, other palette rows keep working, STP bits survive. If
   your edit needs more colors than the row's palette can hold, it quantizes
   with a warning.
2. **Point faces at a different sheet** (in the editor): apply any material
   from the `bg/` collection to a face and compile. v1 requires the TIM to
   already be in that cell's material list — `map2ipd` says so if not.
   New-material support is part of `--full` mode (see below).

The fork's TrenchBroom build also loads raw `.TIM` files as materials
directly (CLUT row 0), useful for previewing custom sheets without exporting
PNGs.

## Editing limits

| Edit | Status |
|------|--------|
| Retexture faces (existing materials) | ✅ v1 |
| UV realignment | ✅ v1 |
| Move vertices/brushes (single-instance models) | ✅ v1 (shared vertices stretch neighbours, like any mesh editor) |
| PSX semi-transparency flag per face | ✅ v1 (surface flag `sh_transparent`) |
| Replace texture pixels (png2tim) | ✅ v1 |
| New/deleted brushes, new materials per cell | `map2ipd --full` (in development) — output can exceed original size, which the port cannot load until the size-cap work in PC_PORT_INTEGRATION.md lands |
| Multi-instance models, shared `_GLB.PLM` | refused by default; `--allow-plm` overrides (edits hit every map using the area) |
| Collision | passthrough only — **moved walls keep their old collision** |
| Entities (spawns, triggers, cameras, doors) | live in map DLLs, not IPDs — future |

## Face metadata contract

`surfaceValue` = face ID into `<AREA>.manifest.json` (provenance: cell,
container, model, mesh, prim, corners). `surfaceFlags`: bit0 = PSX
semi-transparent (renders additively in-game), bit1 = second half of a split
quad, bit2 = global-PLM model. Faces drawn fresh in TrenchBroom have no ID and
are ignored by the v1 compiler (handled by `--full`).

## Troubleshooting

- **Textures all missing in TB**: game path preference lost — re-run
  `install_gameconfig.py` (check Preferences > Games > Silent Hill > Game Path).
- **Compile profile gone**: TrenchBroom rewrote its profile store — re-run
  `install_gameconfig.py`.
- **map2ipd "size changed" assertion**: you hit a bug — in-place mode must
  never change size; report with the .map.
- **Game shows no change after compile**: is `allow_loose_files = 1` set? Was
  the game launched with CWD = its build dir? Set `SH_LOOSE_VERBOSE=1` and
  check SilentHill.log for probe lines. Chunks reload on area re-entry.
- **Editing ER/THR feels risky**: it is — those grids serve many map DLLs.
  Check the table above before editing shared areas.
