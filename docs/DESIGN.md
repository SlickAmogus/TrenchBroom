# Silent Hill 1 Level Editor — Design

Adapting TrenchBroom into a level editor + level compiler for Silent Hill 1 (PSX), targeting
the silent-hill-decomp PC port. This repo is a fork of TrenchBroom/TrenchBroom (branch
`sh1-editor`); all SH-specific work lives in `sh1/` and `docs/`.

Full research reports (byte-level format specs, engine load paths, TB extensibility) are in
`docs/research/`. This doc records the decisions.

## Feasibility verdict

**Feasible, no showstopper.** Verified across all 493 retail IPD files:

- Map geometry+collision is fully self-contained in per-cell `BG/<TAG><XX><ZZ>.IPD` files
  (40×40-unit cells, signed-hex cell coords in the filename). Textures are per-map 4bpp TIMs
  referenced *by material name* embedded in the IPD/PLM. No global state is touched by
  rewriting one cell's IPD.
- The PC port **already has a loose-file override** (`allow_loose_files=1` →
  `gamedata/load/BG/<NAME>.IPD|.TIM`, choke point `src/main/fsqueue_3.c:227-383`), so edited
  files load in-game with **no disc rebuild**, as long as the replacement is ≤ the original's
  sector-aligned size (hard caps: 45056 B exterior / 90112 B interior chunk slot).
- Stock TrenchBroom v2026.1 supports fully data-driven custom games: `GameConfig.cfg` v9 +
  FGD in `%APPDATA%\TrenchBroom\games\SilentHill\`, PNG material dirs, the `Quake3 (Valve)`
  map format (exact per-face affine UVs + 3 abusable per-face metadata numbers), and a
  built-in compile dialog that runs external tools. **v1 needs zero TrenchBroom source
  changes** — the fork exists for later native TIM/IPD support.

## Architecture

```
disc_extract/BG/*.IPD,*.PLM,*.TIM
        │  sh1/tools/ipd2map.py  (extract)
        ▼
<gamedir>/maps/<AREA>.map        Quake3 (Valve) dialect, one TB group per IPD cell
<gamedir>/textures/bg/*.png      one PNG per (TIM, CLUT row) actually used
<gamedir>/maps/<AREA>.manifest.json   face-ID → {ipd, model, mesh, prim, ...} provenance
        │  TrenchBroom (stock v2026.1 binary, custom SilentHill game config)
        ▼  edit: move/retexture/realign, standard TB workflow
<AREA>.map (edited)
        │  sh1/tools/map2ipd.py  (compile; run from TB's Run > Compile Map dialog)
        ▼
gamedata/load/BG/<CELL>.IPD      loose-file override → test in the PC port immediately
```

- **Converters are Python 3** (Python 3.14 + Pillow verified on this machine), in
  `sh1/tools/`. Byte-format authority: `pc_port/src/ipd_reformat.c`, `lm_reformat.c`,
  `include/bodyprog/formats/{ipd,lm,model}.h`, `tools/kaitai_scripts/ipd.ksy` in the decomp
  repo, plus `docs/research/ipd-map-geometry.md` here.
- **Editing container**: `Quake3 (Valve)` .map. Each SH tri/quad becomes a thin prism brush;
  the visible face carries the exact PSX UVs via Valve220 axes; other prism faces get
  `special/skip`. Flat quads whose two PSX triangles share one affine UV map stay single
  quad faces; everything else splits into two triangle brushes.
- **Provenance**: every emitted face gets a sequential integer ID in `surfaceContents`;
  the manifest maps ID → source (cell, model, mesh, prim index, quad half, lighting slots).
  `surfaceFlags` bit0 = isTransparent (additive in-game), bit1 = second half of split quad.
  The compiler uses IDs for exact round-trip; geometry it can't match is recompiled from
  scratch (v2).

## Coordinate convention (LOCKED — everything depends on this)

- SH geometry space is Q23.8 fixed point (256 = 1 world unit), **+Y down**; one map cell =
  10240 Q8 (= 40 units); draw subcell = 2048 Q8 (= 8 units).
- TrenchBroom's hard world bounds are ±32768 (`MapDocument::DefaultWorldBounds`); THR spans
  cells x∈[−8,7] = ±81920 Q8, so 1:1 is impossible.
- **Scale: 1 TB unit = 4 Q8 units** (1 SH world unit = 64 TB units). Exact in binary floats
  (0.25 steps). Cell = 2560 TB, subcell = 512 TB (a power of two — TB grid-friendly).
  Largest area fits: x ±20480, z −20480..28160.
- **Axes: TB.x = SH.x, TB.y = SH.z, TB.z = −SH.y** (proper rotation, det=+1, preserves
  winding). TB +Z is up.
- World position of a vertex: `world_q8 = instanceRot(Q12) · v_q8 + instanceTrans_q8 +
  (cellX·10240, 0, cellZ·10240)`, then map to TB as above and divide by 4.

## Textures

- Export each referenced TIM × CLUT-row pair as `textures/bg/<TIMBASE>_r<NN>.png`
  (256×256 full-page, 128×256 half-page; prim `clut` field is always row·64 on disc —
  verified disc-wide). Face material name = `bg/<TIMBASE>_r<NN>`.
- Color: 5-bit channels expanded `(c<<3)|(c>>2)`; raw texel 0x0000 → alpha 0 (PSX
  transparency rule); STP-set texels stay alpha 255 in v1 (in-game these prims blend
  additively — not representable in TB; the isTransparent bit is preserved in surfaceFlags
  and the IPD keeps the original TIM reference, so game rendering is unaffected).
- `special/skip` + `special/collision` utility textures are generated.

## What the game DLLs vs IPDs own (editing contract)

- IPD (editable via this pipeline): geometry, per-face textures/UVs, model instances,
  draw-order/visibility tables, **collision** (308-byte block at 0x54 + subarrays).
- Map DLL / VIN overlay (NOT touched by v1): triggers (MAP_EVENTS), spawn points
  (MAP_POINTS), room rectangles, cameras, cutscenes, NPC logic. These reference world
  coordinates — moving geometry without updating them changes gameplay meaning.
- Shared data warning: area tags are shared across map DLLs (ER cells serve 11 different
  maps; THR serves 4). `*_GLB.PLM` and TIMs are shared per-area. The editor edits *areas*,
  not map DLLs, and must warn accordingly (manifest records which DLLs consume the area).

## v1 scope (this iteration)

1. `sh1/tools/sh1fmt/` — IPD/LM/PLM/TIM parsers (validated by parsing all 493 IPDs + PLMs).
2. `sh1/tools/ipd2map.py` — area → .map + PNGs + manifest. First target: **DRU** (otherworld
   sewer, 6 IPDs + DRU_GLB.PLM + 12 TIMs — smallest area), then HP (smallest interior).
3. `sh1/games/SilentHill/GameConfig.cfg` + `SilentHill.fgd` + installer script
   (`sh1/tools/install_gameconfig.py`) → `%APPDATA%\TrenchBroom\games\SilentHill\`.
4. Open the converted DRU map fully textured in the stock TB v2026.1 release binary.
5. `sh1/tools/map2ipd.py` — v1 compile: same-topology round-trip (UV edits, material swaps
   among the cell's existing materials, vertex moves; counts unchanged ⇒ size unchanged ⇒
   loose-file safe). Refuses cleanly on topology changes (v2 feature).

## v2+ roadmap

- map2ipd full recompile: re-pack vertex/prim arrays, regenerate modelBuffers AABBs +
  5×5 subcell draw table + modelOrderList (conservative fallback: one buffer covering the
  whole cell, all 25 entries = {0, modelOrderCount}), collision re-pack (needs ptr_18 and
  subcell idA/idB semantics — see research gap list). Validate size ≤ slot caps.
- Billboards + global-PLM instances as FGD point entities with TMD/PLM→glb preview models.
- Entities from map DLLs (spawns, triggers, doors) as point/brush entities; compile emits
  C data patches for pc_port.
- PC-port helper: extend `Map_MakeIpdGrid` (SH_PC_PORT block) to scan `gamedata/load/BG/`
  so *new* cells work without file-table regen; fix the oversized-non-TIM loose-file leak
  (`fsqueue_3.c:161-212`).
- Fork work (only if data-driven v1 UX proves insufficient): native TIM loader
  (`lib/TbMdlLib/src/LoadTexture.cpp:101` dispatch + ~200-line loader), native IPD
  import/export, SH-specific compile task types. Fork build needs VS2022 + Qt 6.10 (Qt not
  yet installed on this machine) — irrelevant until then.

## Known caveats

- The 90112/45056-byte chunk-slot caps are absolute for loose-file testing; ipd2map records
  each cell's original size in the manifest and map2ipd validates against both caps.
- ER2 vs ER MAP_INFOS rows are byte-identical (verified) — treat as one "ER" area.
- TEST/BTT_*.IPD are retail-format for geometry but violate collision invariants — parser
  fixtures only, never collision fixtures.
- Lighting: per-vertex brightness is computed at runtime (baked lighting slots are vertex
  indices grouped by normal — verified disc-wide, ~830k slots). The editor shows unlit
  texels; that is correct-enough for texturing/geometry work.
