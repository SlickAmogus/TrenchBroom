# Research: textures-tim-vram

## Summary

Silent Hill 1 map textures are per-map 4bpp 256x256 (or 128x256 "half-page") TIM files in disc_extract/BG/, named after the material names embedded in each map chunk's IPD file (LM sub-header) plus the map's *_GLB.PLM. At runtime the engine assigns each TIM one of 10 fixed VRAM slots (8 full pages at tpage ids 8,9,10,21-25; 2 half pages sharing tpage 26) and uploads its 16xN CLUT to VRAM row 0 at x=slot*16; on disc all material base fields are zero, so prim UVs are already TIM-relative texels and prim clut values are exactly 64*CLUT-row. PsyCross keeps raw PSX VRAM in a CPU u16[1024*512] array and decodes 4bpp+CLUT in the fragment shader with RGBA5551 semantics (texel 0x0000 = discard/transparent, STP bit = alpha 0.5, channels c/32). A working TIM→PNG converter already exists at pc_port/tools/tim_convert.py (its 4bpp path only exports CLUT row 0 — map TIMs need per-row export). The offline recipe reduces to: parse IPD LM materials → material name + ".TIM" → decode TIM with CLUT row = prim.clut/64 → per-vertex u,v index texels directly.

# Silent Hill 1 Map Textures — End-to-End

## 1. Where map TIMs live and naming

**Location**: Map (world/terrain) textures are NOT in `disc_extract/TIM/` — they are in **`C:/Claude/silenthill/disc_extract/BG/`** alongside the geometry files. `disc_extract/TIM/` (211 files) holds UI/item/event fullscreen textures loaded by explicit `FILE_TIM_*` code paths. `BG/` has 1200 files: 694 `.TIM`, ~470 `.IPD` (terrain chunks), plus `*_GLB.PLM` (shared model libraries per exterior map: `THR_GLB.PLM`, `APR_GLB.PLM`, `APU_GLB.PLM`, `DR_GLB.PLM`, `DRU_GLB.PLM`, `SPR/SPU/RSR/RSU...`) and `BG_ITEM.PLM`.

**Naming convention**: `<materialName>.TIM`, where materialName is the 8-char name stored in the map's material list. Convention observed: map tag + index + `F` (full page) or `H` (half page), e.g. `THR0001F.TIM`, `THR0702H.TIM`, `APU01F.TIM`, `APU01H.TIM`. The `F`/`H` suffix is semantically load-bearing: `LmFilter_IsHalfPage` returns true iff the LAST non-NUL char of the material name is `'H'` (`src/bodyprog/gfx/bodyprog_80040B74.c:2271-2286`; `LmFilter_IsFullPage` is its negation at :2263).

**Formats**: ALL 694 BG TIMs are **4bpp** (verified by running `tim_convert.py info` over the whole dir: 694x "4bpp"). Full-page TIMs are 256x256 texels (stored width 64 u16), half-page are 128x256 (stored 32 u16). CLUTs are **16 entries wide x N rows** (N up to 16, e.g. `THR0001F` 16x6, `THR0201F` 16x12, `THR02H2F` 16x16). Multiple rows = alternate palettes for different polygons sharing one page (each prim picks its row, see §5). All BG TIM headers carry pix rect (0,0) and clut rect (0,0) — the on-disc VRAM coords are dummies; the engine overrides them at load (§3).

**TIM file format** (documented in `pc_port/tools/tim_convert.py:56-84`): u32 magic 0x10; u32 flags (bits0-2 pmode: 0=4bpp,1=8bpp,2=16bpp,3=24bpp; bit3 = has CLUT); optional CLUT block {u32 size, u16 x,y,w,h, u16 entries[w*h]}; pixel block {u32 size, u16 x,y, u16 storedW,h, data}. Pixel: 16-bit A1B5G5R5 little-endian — R=bits0-4, G=5-9, B=10-14, STP=bit15. 4bpp packs two indices per byte, **low nibble = left pixel** (tim_convert.py:214-216).

## 2. How the game knows which TIMs a map uses

There is no per-map TIM list. Chain:

1. Each map overlay header names a terrain type: e.g. `src/maps/map0_s01/map0_s01_header.c:39` → `.mapInfo = &MAP_INFOS[MapType_THR]`. School = `MapType_SC` (map1_s00/s01/s06), streets = `MapType_THR` (map0_s00, map0_s01, map2_s00, map2_s03). Enum at `include/bodyprog/map/map.h:87-107`.
2. `MAP_INFOS` (`src/bodyprog/sys/map_info.c:468-485`) maps type → 2-4 char tag (`"THR"`, `"SC"`, `"APU"`, ...) + global PLM file (`FILE_BG_THR_GLB_PLM` for exteriors, `NO_VALUE` for interiors) + interior flag.
3. `Ipd_PlayerChunkInit` (`src/bodyprog/gfx/world_draw.c:178-241`, call at :233) passes tag+plmIdx to `Ipd_MapFileInfoSet` (`src/bodyprog/gfx/bodyprog_80040B74.c:668`), which stores them and calls `Map_MakeIpdGrid` (:846-895). That scans the ENTIRE file table for `FileType_Ipd` entries whose name starts with the tag and parses the next 4 chars as **two signed hex bytes = cellX, cellZ** (`ConvertHexToS8` :897). So `THRFEFD.IPD` = tag THR, cell x=-2, z=-3. Grid is 16x19 cells centered at `chunkGrid[8].idx[8]`.
4. When a chunk IPD loads, `IpdHeader_FixOffsets` (:2165) → `Ipd_MaterialsLoad` (:2235) → `Lm_MaterialsLoadWithFilter` (`src/bodyprog/gfx/bodyprog_80055028.c:1257`) walks the chunk's **material list** (inside the IPD, §4). For each unresolved material, `Texture_Get` (:4072) takes the 8-char material name, appends `".TIM"` (`Material_TimFileNameGet` :4169-4185), finds it by name via `Fs_FindNextFile`, and queues `Fs_QueueStartReadTim(fileId, FS_BUFFER_9, &slot->imageDesc)` (:4141). The global PLM's materials load the same way into the full-page pool (`bodyprog_80040B74.c:1219`, :1320, filter=NULL).

So: **the TIM set of a map = union of material names in all its IPD files + its *_GLB.PLM**. File table entry format: `s_FileInfo` {startSector:19, blockCount:12 (256-byte blocks), pathIdx:4, packed 8-char name, type:4} — `include/main/fileinfo.h:55-64`; human-readable copy at `disc_extract/filetable.c.inc` (e.g. line 1073: `THR0000 ` type 6 = BG/THR0000.IPD) and `disc_extract/fileenum.h.inc`.

## 3. Runtime VRAM layout

Fixed slot table built by `Ipd_TexturesInit` (`src/bodyprog/gfx/bodyprog_80040B74.c:528-559`), stored in `g_Map.chunkTextures` (`include/bodyprog/map/terrain.h:40-54`: 8 fullPageTextures + 2 halfPageTextures, each an `s_Texture` with an `s_FsImageDesc {u8 tPage[2]; u8 u,v; s16 clutX, clutY}` — `include/main/fsqueue.h:217-225`):

| slot | tPage[1] (tpage id) | VRAM page origin | u offset | CLUT (x,y) |
|------|-----|------------------|----------|------------|
| full 0-2 | 8, 9, 10 | (512,0) (576,0) (640,0) | 0 | (0,0) (16,0) (32,0) |
| full 3-7 | 21,22,23,24,25 | (320,256)...(576,256) | 0 | (48,0)...(112,0) |
| half 0 | 26 | (640,256) left half | u=0 | (128,0) |
| half 1 | 26 | (640,256) right half | u=32 halfwords (=texel 128) | (144,0) |

tpage id decode: pageX = (id & 0xF)*64 halfwords, pageY = (id & 0x10) ? 256 : 0. `tPage[0]` = color depth (0=4bpp → UV coeff 4; 1=8bpp → 2; 2=16bpp → 1) — see `Material_FsImageApply` switch (`bodyprog_80055028.c:1192-1206`). Map slots are always 4bpp (tPage[0]=0).

**Upload**: `Fs_QueuePostLoadTim` (`src/main/fsqueue_3.c:517-592`) parses the TIM (`OpenTIM`/`ReadTIM`), then **overrides** the TIM's own rects: pixel dest x = `image.u + ((tPage[1] & 0xF) << 6)`, y = `image.v + ((tPage[1] << 4) & 0x100)` (:553-556), then `LoadImage(&rect, tim.paddr)` (:563); CLUT dest = (`image.clutX`, `image.clutY`) if clutX != -1, then `LoadImage(&rect, tim.caddr)` (:574-587). A 16xN CLUT therefore lands at VRAM (slot.clutX, rows 0..N-1). Framebuffers sit at (0,32) and (0,256), 320x224 (`src/bodyprog/screen/screen_draw.c:42-46`, `GsDefDispBuff2(0, 32, 0, 256)`; `include/game.h:25`), so VRAM rows 0-31 in x∈[0,320) are free for the CLUT strip.

**PSX CLUT id encoding** (used in prims): `clut = (y << 6) | (x >> 4)` — see `Material_FsImageApply` (`bodyprog_80055028.c:1216-1217`) and PsyCross `GET_CLUT_X/GET_CLUT_Y` (`pc_port/PsyCross/src/gpu/PsyX_GPU.cpp:20-21`).

## 4. On-disc IPD/LM/material/prim formats (offline parsing)

Authoritative parsers: `pc_port/src/ipd_reformat.c` and `pc_port/src/lm_reformat.c` (they read the raw PSX 32-bit layout).

**IPD file** (ipd_reformat.c:18-26): 0x00 magic(=20)/isLoaded/cellX/cellZ; 0x04 u32 **lmHdr offset** (from file start); 0x08 modelCount/modelBufferCount/modelOrderCount; 0x14 modelInfo off; 0x18 modelBuffers off; 0x50 modelOrderList off; 0x54 collision data (308B).

**LM header** (at lmOff; also the entire content of a .PLM file, offset 0): byte0 magic '0'(0x30), byte1 version 6, byte2 isLoaded, byte3 materialCount; u32@4 materials offset; byte8 modelCount; u32@12 modelHdrs offset; u32@16 modelOrder offset (lm_reformat.c:100-120). All offsets relative to LM header start.

**s_Material, 24 bytes on disc** (`include/bodyprog/formats/lm.h:11-32`, parse at lm_reformat.c:77-90): 0x0 name[8] (TIM base name); 0x8 texture ptr (0 on disc); 0xC field_C (1 = manually-applied, skip auto-load); 0xE field_E / 0xF field_F = current/previous **tpage attribute byte**; 0x10/0x12 field_10/field_12 = current/previous **clut id base**; 0x14/0x16 field_14/field_16 = current/previous **UV base** (u8 u, u8 v). **Verified on THR0001.IPD: all six materials have field_E/F = field_10/12 = field_14/16 = 0** — i.e. on disc, prim UV/clut/tpage values are relative to a ZERO base.

**s_Primitive, 20 bytes** (`include/bodyprog/formats/model.h:5-25`): field_0=(u0,v0), field_2=clut, field_4=(u1,v1), field_6 = {bits0-7 tpage byte, bits8-14 materialIdx (s7, -1 = untextured), bit15 isTransparent}, field_8=(u2,v2), field_A=(u3,v3), field_C[4]=vertex indices, field_10[4]=indices into meshHdr->unkPtr_14 (baked per-vertex shading table). Mesh header (24B): counts + offsets to prims / DVECTOR verticesXy / s16 verticesZ / normals / unkPtr_14 (lm_reformat.c:35-46).

**Runtime rebasing** (`Model_MaterialFlagsApply`, `bodyprog_80055028.c:1427-1469`): when a material's texture slot is (re)assigned, every prim with that materialIdx gets `field_6_0 = mat.field_E`, `field_2 = mat.field_10 + (field_2 - mat.field_12)`, `field_0/4/8/A = mat.field_14 + (old - mat.field_16)` (u16 arithmetic, u in low byte, v in high). New bases from `Material_FsImageApply` (:1188-1218): `field_14 = (image.u * coeff, image.v)`; `field_E = ((tPage0&3)<<7) | ((blendMode&3)<<5) | (tPage1&0x10) | (tPage1&0xF)`; `field_10 = (clutY<<6) | (clutX>>4)`. Map materials always load with `BlendMode_Additive` (=1, `include/gpu.h:55-60`; call sites `bodyprog_80040B74.c:2244,2249`), so semi-transparent map prims (isTransparent bit) blend **additively**.

**Verified prim dump** (THR0001.IPD, model 0): clut values 128/320/832 = 64x{2,5,13} → CLUT row index x64; UVs are direct texel coords 0-255. tpage byte 0 on disc.

**Draw emit** (`bodyprog_80055028.c:4009-4028`): `POLY_GT4.code = ((flags>>15)*2) | 0x3C` (bit1 = ABE semi-transparency from isTransparent); u0/v0/clut word = `prim.field_0` (+ optional global CLUT-row shift `g_WorldEnvWork.field_14C << 16`, :3801 — passed as 0 for all map terrain, `bodyprog_80040B74.c:2449,2485,2520`); u1/v1/tpage word = `prim.field_4` with tpage = field_6_0.

## 5. PsyCross (PC) color conversion

PsyCross does NOT pre-convert to GL textures. It keeps a CPU mirror of PSX VRAM: `unsigned short vram[1024*512]` (`pc_port/PsyCross/src/render/PsyX_render.cpp:724`); `LoadImage` = `GR_CopyVRAM` memcpy into it (`pc_port/PsyCross/src/psx/libgpu.c:74-78`). The whole array uploads as one two-byte-per-texel GL texture, and **CLUT decode happens in the fragment shader**:

- 4bpp sampler (`PsyX_render.cpp:918-930`): fetch u16 at (pageX + u/4, pageY + v); pick nibble u%4; CLUT texel at (clutX + nibble, clutY); returns 16-bit value.
- Page/clut from vertex attrs (`:1034-1037`): pageX=(tpage%16)*64, pageY=floor(tpage/16)*256, clutX=(clut&63)/64 of 1024, clutY=(clut>>6).
- `decodeRG` (`:835-839`): R=bits0-4, G=5-9, B=10-14 each mapped to **c/32** float; alpha = 0 if raw==0x0000, 0.5 if STP bit set, else 1.0.
- **Black-transparent rule**: `NearestTextureSample` discards any texel whose 16-bit value == 0 (`:970-975`); bilinear path discards when the bilinear "presence" weight < 0.5 (`:952-968`).
- Blending (`:3400-3412`): BM_AVERAGE → `glBlendFunc(GL_SRC_ALPHA, ONE_MINUS_SRC_ALPHA)` (STP alpha 0.5 halves), BM_ADD/BM_SUBTRACT → `GL_ONE,GL_ONE` (subtract uses REVERSE_SUBTRACT equation), BM_ADD_QUATER → CONSTANT_ALPHA. tpage attribute decode macros: `PsyX_GPU.cpp:15-21`.

Offline PNG equivalent per texel: `if raw==0 → RGBA(0,0,0,0); else RGB = (c5<<3)|(c5>>2) per channel (or c5/31), A = 255 (STP only matters if the prim has isTransparent set → render additive)`.

## 6. Existing TIM tooling

- **`C:/Claude/silenthill/silent-hill-decomp/pc_port/tools/tim_convert.py`** — full TIM↔PNG converter (extract/pack/info subcommands, Pillow). Handles 4/8/16/24bpp, black+STP=0 → alpha 0. **Limitation for map TIMs**: 4bpp decode uses only CLUT **row 0** (line 217-220 comment acknowledges it) — map TIMs need row selection per material/prim.
- **SHModelViewer** (`C:/Claude/silenthill/SHModelViewer/src/main.c:12`): explicitly "Textures (TIM->VRAM) are a later step" — no TIM support yet.
- No TIM scripts in `disc_extract/` itself (its .py-less; README/USAGE are vgmstream docs).
- The PC port also has a hi-res TIM override pipeline (loose file replacement, `src/main/fsqueue_3.c:596+`, `pc_port/src/hires_override.c`) keyed by (tpage, clut) — useful precedent for editor-side texture injection.

## 7. Example map: THR (streets — map0_s00 "old town", map0_s01, map2_s00, map2_s03)

- Declared via `.mapInfo = &MAP_INFOS[MapType_THR]` (`src/maps/map0_s00/map0_s00_header.c:43`, `map0_s01_header.c:39`).
- MAP_INFOS[0] = `{FILE_BG_THR_GLB_PLM, "THR", MapFlag_FourActiveChunks, NULL, SPEED_ZONES_THR}` (`src/bodyprog/sys/map_info.c:469`).
- Terrain chunks: all `disc_extract/BG/THR????.IPD` where ???? = signed hex cellX,cellZ (128 files, e.g. THR0000.IPD, THRFEFD.IPD). One special-case: `Map_PlaceIpdAtCell(FILE_BG_THR05FD_IPD, -1, 8)` (`world_draw.c:235-238`).
- Textures: whatever each IPD's material list names. E.g. THR0001.IPD (cell 0,1) → materials `THR0001F, THR0003F, THR1201F, THR0004F, THR0002F, THR1202H` → those 6 .TIM files in BG/ (5 full-page + 1 half-page). Plus THR_GLB.PLM's own materials (e.g. `AMBCARF`/`AMBCARH` → ambulance textures). The full THR texture set = 171 THR*.TIM files.

## 8. Offline recipe: render any map polygon fully textured

1. Pick map → tag via header's MAP_INFOS entry (§7). Collect `BG/<TAG>XXZZ.IPD` (signed-hex cells) + `BG/<TAG>_GLB.PLM`.
2. Parse IPD: u32@0x04 → LM header; parse LM per §4 (PLM = LM at offset 0).
3. For each material i: `timName = trim(name) + ".TIM"` → load from `disc_extract/BG/`. All bases are zero on disc, so no rebasing math is needed.
4. For each mesh prim with materialIdx == i: vertices = verticesXy[field_C[k]] + verticesZ[field_C[k]] (s16, model-local; instance transform = 32-byte PSX MATRIX in modelBuffers, ipd_reformat.c:63-80, plus cell-origin offset at draw, bodyprog_80040B74.c:2445-2448).
5. Texture sample for vertex k with (u,v) from field_0/4/8/A: `clutRow = prim.field_2 / 64`; `byte = timPixels[v * storedW*2 + u/2]`; `idx = (byte >> ((u&1)*4)) & 0xF`; `c16 = clut[clutRow*16 + idx]`; `c16 == 0 → transparent (discard)`; else RGB = 5-bit channels R=bits0-4,G=5-9,B=10-14 expanded; if `prim.field_6 & 0x8000` render the polygon additively (STP-set texels especially); modulate by baked vertex shading `meshHdr->unkPtr_14[prim.field_10[k]]` if fidelity to in-game lighting is wanted (neutral = treat 128 as 1.0, PSX modulation convention).
6. Half-page TIMs need no special handling offline — their UVs are already 0-127 TIM-relative; the +128 texel offset only exists at runtime for slot 1 (image.u=32 halfwords x coeff 4).
7. To reverse a RUNTIME polygon (from RAM/logs) back to a TIM: tpage byte bits0-4 → page id → slot (8,9,10,21-25 full; 26 half, split by u<128) → `s_Texture.name` → TIM file; clut id: row = clut>>6, slot = clut&0x3F (clutX/16); TIM-relative texel u = abs_u − (slot==half1 ? 128 : 0).

## Key files

- C:/Claude/silenthill/silent-hill-decomp/src/bodyprog/gfx/bodyprog_80040B74.c — Map streaming core: Ipd_TexturesInit VRAM slot table (:528), Ipd_MapFileInfoSet (:668), Map_MakeIpdGrid tag+hex-cell IPD discovery (:846), IpdHeader_FixOffsets/Ipd_MaterialsLoad (:2165/:2235), full/half-page name filters (:2263-2286)
- C:/Claude/silenthill/silent-hill-decomp/src/bodyprog/gfx/bodyprog_80055028.c — Material/texture engine: Material_FsImageApply tpage/clut/UV base encode (:1188), Model_MaterialFlagsApply prim rebasing (:1427), Texture_Get slot allocation+TIM lookup by name (:4072), Material_TimFileNameGet (:4169), GT4 emit with clut/tpage packing (:4009)
- C:/Claude/silenthill/silent-hill-decomp/src/main/fsqueue_3.c — Fs_QueuePostLoadTim (:517): decodes TIM, overrides pixel dest from tPage[1]/u/v (:553-556) and CLUT dest from clutX/clutY, LoadImage into VRAM; also hi-res override hook
- C:/Claude/silenthill/silent-hill-decomp/pc_port/src/lm_reformat.c — Authoritative on-disc byte layout of LM header / model / mesh / 24-byte material (ParseMaterial :77)
- C:/Claude/silenthill/silent-hill-decomp/pc_port/src/ipd_reformat.c — Authoritative on-disc IPD layout (header comment :18-26); PSX 32-byte MATRIX parse for model instances (:63-80)
- C:/Claude/silenthill/silent-hill-decomp/pc_port/PsyCross/src/render/PsyX_render.cpp — PC color conversion: vram[1024*512] u16 (:724), 4/8/16bpp shader samplers (:918-949), decodeRG 5551 + STP alpha + zero-discard (:835-839, :970-975), blend funcs (:3400)
- C:/Claude/silenthill/silent-hill-decomp/pc_port/tools/tim_convert.py — EXISTING TIM->PNG/PNG->TIM converter + header dumper; 4bpp path exports CLUT row 0 only — extend for per-row map palettes
- C:/Claude/silenthill/silent-hill-decomp/src/bodyprog/sys/map_info.c — MAP_INFOS[16] (:468-485): map tag, global PLM file index, interior flag per MapType
- C:/Claude/silenthill/silent-hill-decomp/include/bodyprog/formats/lm.h — s_Material (24B) and s_LmHeader structs (binary-identical to disc except pointers)
- C:/Claude/silenthill/silent-hill-decomp/include/bodyprog/formats/model.h — s_Primitive 20-byte layout: per-vertex UV, clut, tpage byte, materialIdx, isTransparent, vertex/shading indices
- C:/Claude/silenthill/silent-hill-decomp/include/bodyprog/map/terrain.h — s_ChunkTextures: 8 full-page + 2 half-page texture slots; s_MapTerrain grid
- C:/Claude/silenthill/disc_extract/BG — All map terrain data: *.IPD chunks, *_GLB.PLM shared models, 694 4bpp map TIMs named <material>.TIM
- C:/Claude/silenthill/silent-hill-decomp/include/main/fileinfo.h — s_FileInfo file-table entry format + FileType enum (Tim=0, Plm=5, Ipd=6)
- C:/Claude/silenthill/disc_extract/filetable.c.inc — Readable dump of the 2074-entry file table with names, types, sectors

## Open questions

- s_Primitive.field_10[4] indexes meshHdr->unkPtr_14 (per-vertex baked shading, fed to GTE as light vector via gte_ldsv<<5 in bodyprog_80055028.c:2431); exact photometric interpretation (scale, interaction with worldTint/fog in MAP_EFFECTS_INFOS) was not fully traced — matters only for reproducing in-game lighting, not raw texturing
- Whether any prim clut delta ever encodes a column offset rather than row*64 (all sampled THR prims were clean multiples of 64; a full-disc scan of all IPDs would confirm)
- The multi-row CLUTs' authoring intent (day/dark palette variants vs. simply >16 colors per page split across rows) — engine-side the row choice is fully static per prim for map terrain (g_WorldEnvWork.field_14C CLUT-shift is always 0 for chunks, used only for character models)
- tim_convert.py 4bpp export must be extended to emit one image (or palette) per CLUT row before it can round-trip map TIMs losslessly for the editor
- Interior maps (SC/SU/ER/HP/HU) use only per-IPD materials (no global PLM, MAP_INFOS plmFileIdx=NO_VALUE) — verified from the table, but the interior chunk-texture steal/return pool (g_PcInteriorMatSync, bodyprog_80055028.c:1332-1359) means runtime tpage values for interiors are dynamic; offline tools should ignore runtime slots and key purely by material name
