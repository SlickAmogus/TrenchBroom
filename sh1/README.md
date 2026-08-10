# Silent Hill 1 Level Editor (TrenchBroom-based)

Edit real Silent Hill 1 (PSX) map geometry and textures in TrenchBroom and load
the result in the silent-hill-decomp PC port — no disc rebuild required.

**Status: working.** The full loop (convert → edit → compile → see it in game)
has been confirmed end to end, including a texture change visible in the
otherworld sewer.

- Design + decisions: `../docs/DESIGN.md`
- Byte-level format research: `../docs/research/`
- Shipping it to other people: `../docs/DISTRIBUTION.md`
- Engine-side roadmap (size caps, new cells, custom assets): `../docs/PC_PORT_INTEGRATION.md`

## Requirements

- **TrenchBroom v2026.1+** — either the stock release or this fork's build
  (the fork adds native `.TIM` loading; everything else works on stock).
- **Python 3** with **Pillow** (`pip install pillow`).
- **Extracted disc assets** — a folder containing `BG/` full of `.IPD` files.
  Produce it from your own disc image with
  `silent-hill-decomp/tools/silentassets/extract.py`. Not distributable.
- **The PC port build** (only needed to test in game).

## One-time setup

```bat
cd sh1\tools
python setup_paths.py          :: finds/asks for the 3 paths, saves sh1paths.json
python install_gameconfig.py   :: installs the TrenchBroom game config
```

`setup_paths.py` auto-detects the usual layout; accept the defaults if they look
right. Paths can also come from `SH1_DISC` / `SH1_GAMEDIR` / `SH1_PORT`
environment variables or per-command flags. `python setup_paths.py --show`
prints what the tools currently resolve.

`install_gameconfig.py` writes into `%APPDATA%\TrenchBroom\games\SilentHill\`:
the game config + FGD, a **Run > Compile Map** profile, and a **Run > Launch
Engine** profile. It also points TrenchBroom's game path at your editor game
dir. Re-run it any time — it's idempotent and restores profiles TrenchBroom's
UI overwrote.

Finally, in the port's `config.cfg`, set `allow_loose_files = 1`. Without it the
game ignores everything you compile.

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

Before replacing a texture, check who else uses it:
`python tim_owners.py DRU01F` or `python tim_owners.py --shared`.

## The edit loop

```bat
:: 1. convert an area (writes <gamedir>\maps\<AREA>.map + textures + manifest)
python ipd2map.py --area DRU

:: 2. open in TrenchBroom
TrenchBroom.exe <gamedir>\maps\DRU.map

:: 3. edit: retexture faces (material browser, "bg" collection), realign UVs,
::    move vertices/brushes. The face attribute "value" is the round-trip ID -
::    do not edit it by hand.

:: 4. compile: Run > Compile Map > "Compile to game (loose files)"
::    (or: python map2ipd.py --map <gamedir>\maps\DRU.map)
::    -> writes changed cells to <port>\gamedata\load\BG\

:: 5. test: Run > Launch Engine, then walk into the area.
```

`map2ipd` only writes cells that actually changed, patches them in place
(output size == original, always loose-file safe), and prints exactly what it
did. Compiling an unedited map writes nothing — the pipeline is byte-exact in
both directions.

Chunks reload when you re-enter an area, so you do not always need a restart.

## Custom textures

**Preferred: hi-res PNG overrides.** Repaint an exported sheet
(`<gamedir>\textures\bg\<SHEET>_r<NN>.png`) at any resolution, in full colour,
then:

```bat
python textures_to_game.py --area DRU        :: pushes only sheets you edited
python textures_to_game.py --sheet DRU01F --dry-run
python textures_to_game.py --clean --area DRU
```

This writes `<port>\gamedata\load\BG\<SHEET>.TIM.p<NN>.png`, which the port
loads as a hi-res override — **no 16-colour palette limit and no size limit**.
A per-row set must include row `p00`; if a sheet does not change in game, export
and push its row 0 too.

**Alternative: a real 4bpp TIM.** When something must stay a genuine disc-format
file, `png2tim.py` packs a PNG back into the TIM's palette:

```bat
python png2tim.py --png edited.png --tim <disc>\BG\DRU01F.TIM --row 1
```

Packing is identity-preserving: untouched pixels keep their exact bytes, other
palette rows keep working, STP bits survive. Edits needing more colours than the
row's palette holds are quantized with a warning.

The fork's TrenchBroom build also loads raw `.TIM` files as materials directly
(CLUT row 0), useful for previewing sheets without exporting PNGs.

## Editing limits

| Edit | Status |
|------|--------|
| Retexture faces (materials already in the cell) | works |
| UV realignment | works |
| Move vertices/brushes (single-instance models) | works — shared vertices stretch neighbours, like any mesh editor |
| PSX semi-transparency flag per face | works (surface flag `sh_transparent`) |
| Replace texture pixels, any resolution | works (`textures_to_game.py`) |
| New/deleted brushes, new materials per cell | `map2ipd --full` produces correct files, but output usually **exceeds the original size, and the port then ignores it** — needs the size-cap work in PC_PORT_INTEGRATION.md |
| Multi-instance models, shared `_GLB.PLM` | refused by default; `--allow-plm` overrides (edits hit every map using the area) |
| Collision | passthrough only — **moved walls keep their old collision** |
| Entities (spawns, triggers, cameras, doors) | live in map DLLs, not IPDs — future |

## Verifying

```bat
python validate_formats.py       :: parse every disc IPD/PLM/TIM, check invariants
python validate_writer.py        :: re-serialize all 493 IPDs, require byte identity
python validate_port_compat.py <dir>   :: would the PC port accept these files?
```

`validate_port_compat.py` matters: the port validates IPD headers before loading
and **silently skips** files that fail, which looks exactly like "my edit did
nothing". Run it on compiler output when a change refuses to appear.

There is also a staged in-game smoke test for the loose-file loader:

```bat
python loose_smoke_test.py 1   :: unmodified IPD copy -> must look normal
python loose_smoke_test.py 2   :: every DRU sheet striped red
python loose_smoke_test.py 3   :: retextured + raised water tile
python loose_smoke_test.py clean
```

The loose path is CWD-relative: launch the game from its own build directory.
`SH_LOOSE_VERBOSE=1` logs every loose-file probe to SilentHill.log.

## Face metadata contract

`surfaceValue` = face ID into `<AREA>.manifest.json` (provenance: cell,
container, model, mesh, prim, corners). `surfaceFlags`: bit0 = PSX
semi-transparent (renders additively in-game), bit1 = second half of a split
quad, bit2 = global-PLM model. Faces drawn fresh in TrenchBroom have no ID and
are ignored unless you compile with `--full`.

## Troubleshooting

- **Tools can't find anything** — run `python setup_paths.py --show`, then
  `python setup_paths.py` to fix.
- **Textures all missing in TrenchBroom** — game path preference lost; re-run
  `install_gameconfig.py` (check Preferences > Games > Silent Hill > Game Path).
- **Compile profile gone** — TrenchBroom rewrote its profile store; re-run
  `install_gameconfig.py`.
- **Game shows no change after compile** — check, in order: `allow_loose_files = 1`
  in the port's `config.cfg`; the game launched with its build dir as the working
  directory; `python validate_port_compat.py <port>\gamedata\load\BG` reports no
  rejects; you re-entered the area. Then set `SH_LOOSE_VERBOSE=1` and look for
  `[LOOSE]` / `[IPD-VAL]` lines in SilentHill.log.
- **`--full` output ignored by the game** — expected today; its output exceeds
  the original file size. See PC_PORT_INTEGRATION.md.
- **map2ipd "size changed" assertion** — a bug; in-place mode must never change
  size. Report it with the .map.
- **Editing ER/THR feels risky** — it is; those grids serve many map DLLs.
