# Research: ipd-map-geometry

## Summary

Documented the SH1 map geometry pipeline at byte level. An .IPD file is a per-40×40-unit-cell chunk containing: an 0x84-byte header (offsets to model-instance tables, a 5×5 subcell draw table, and a draw-order list), a 308-byte embedded collision block (heightfield-ish subcell/surface data with its own sub-arrays, offsets relative to file+0x54), and an embedded LM model archive (magic 0x30 v6) holding materials + models + meshes + 20-byte quad/tri primitive packets rendered as POLY_GT4/GT3/FT4. .PLM files are the exact same LM format standalone (per-map *_GLB.PLM global models and ITEM/*.PLM item models). All pointers on disc are little-endian u32 file-relative offsets, relocated in place at load (IpdHeader_FixHeaderOffsets / LmHeader_FixOffsets / Ipd_CollisionPtrsInit); pc_port/src/ipd_reformat.c and lm_reformat.c are complete byte-accurate C parsers, and tools/kaitai_scripts/ipd.ksy is an existing Kaitai spec. Chunk streaming maps IPD filenames (mapTag + 2-hex-digit signed cellX + 2-hex cellZ) onto a 16×19 cell grid at 40 world units per cell; 4 chunks stream for exteriors, 1-2 for interiors, into a 0x2C000-byte buffer. Layout claims verified against a real file (BG/APU0000.IPD hexdump).

# Silent Hill 1 Map Geometry Formats (.IPD / .PLM) — Byte-Level Reference

All multi-byte values are **little-endian**. All "offset" fields on disc are u32 **file-relative byte offsets** (two exceptions noted below). The engine relocates them in place after load by adding the load address — see `IpdHeader_FixHeaderOffsets` (src/bodyprog/gfx/bodyprog_80040B74.c:2288), `LmHeader_FixOffsets` (src/bodyprog/gfx/bodyprog_80055028.c:1036), `ModelHeader_FixOffsets` (:1060), `Ipd_CollisionPtrsInit` (src/bodyprog/collision/collision.c:179). The PC port instead re-parses the raw bytes: **pc_port/src/ipd_reformat.c and pc_port/src/lm_reformat.c are, field-for-field, the parser you want to transcribe to Python.** A community Kaitai spec also exists: tools/kaitai_scripts/ipd.ksy (plus ilm.ksy, anm.ksy).

## 0. Coordinate system & units

- World logic runs in Q19.12 (4096 = 1 unit); geometry/"map space" is Q23.8 (256 = 1 unit). Conversions via `Q12_TO_Q8` etc. (include/bodyprog/math/fixed_point.h:270,286).
- +Y is **down** (PSX GTE convention); e.g. a model instance floating 1 unit above ground has t[1] = -256 (verified in APU0000.IPD instance dump).
- One map cell = `CHUNK_CELL_SIZE` = 40.0 units (include/game.h:29, `Q12(40.0f)`), i.e. 10240 in Q8. Cell (cx,cz) covers world X ∈ [cx·40, cx·40+40), Z ∈ [cz·40, cz·40+40) (Ipd_DistanceToEdgeGet, bodyprog_80040B74.c:1353-1370).
- Draw subcells: 5×5 per cell, 8.0 units each (`CHUNK_SUBCELL_SIZE Q8(8.0)`, bodyprog_80040B74.c:2391,2418-2423).
- Vertex/matrix-translation coordinates inside geometry are s16/s32 **Q8** (256 = 1 unit); rotation matrices are Q12 (4096 = 1.0).

## 1. .IPD file — top-level layout

One IPD = one terrain chunk for one grid cell. Header (PSX size **0x188**: 0x54 header + 0x134 collision), verified against `disc_extract/BG/APU0000.IPD`:

| off | size | field | notes |
|-----|------|-------|-------|
| 0x00 | u8 | magic | must be **0x14** (`IPD_HEADER_MAGIC`, include/bodyprog/formats/ipd.h:7) |
| 0x01 | u8 | isLoaded | runtime flag; **undefined garbage on disc** (ipd_reformat.c:270-273 explicitly distrusts it) |
| 0x02 | s8 | cellX | grid X (also encoded in filename) |
| 0x03 | s8 | cellZ | grid Z |
| 0x04 | u32 | lmHdrOff | file offset of embedded LM header (geometry archive, §3) |
| 0x08 | u8 | modelCount | size of modelInfo array |
| 0x09 | u8 | modelBufferCount | size of modelBuffers array |
| 0x0A | u8 | modelOrderCount | size of modelOrderList |
| 0x0B | u8+u8[8] | unknown | always 0 in samples; preserved blindly (ipd_reformat.c:289,299-301) |
| 0x14 | u32 | modelInfoOff | → s_IpdModelInfo[modelCount], stride 16 |
| 0x18 | u32 | modelBuffersOff | → s_IpdModelBuffer[modelBufferCount], stride 24 |
| 0x1C | u8[5][5][2] | subcell draw table | **not** a "textureCount" — for viewer subcell (sx,sz): byte pair at `0x1C + sz*10 + sx*2` = {start, count} into modelOrderList (Ipd_ChunkDraw, bodyprog_80040B74.c:2500-2503). 50 bytes + 2 pad |
| 0x50 | u32 | modelOrderListOff | → u8[modelOrderCount]; each entry is an index into modelBuffers (draw order per subcell) |
| 0x54 | 0x134 | collision block | §2. **Its internal offsets are relative to file offset 0x54**, not 0 |

The header struct in ipd.h names offset 0x1C `textureCount` + `unk_1D[51]` — that is a misnomer kept for layout; the draw code indexes it as the 5×5 table.

Sample (APU0000.IPD): magic 0x14, lmHdrOff 0x1B84, modelCount 34, modelBufferCount 4, modelOrderCount 25, modelInfoOff 0x188, modelBuffersOff 0x3A8, modelOrderListOff 0xCBC.

### s_IpdModelInfo — 16 bytes each (ipd.h:114-121; ipd_reformat.c:48-55)

| off | size | field |
|-----|------|-------|
| 0x0 | u8 | isGlobalPlm — 0: model lives in this IPD's embedded LM; 1: resolve by name from the map's `*_GLB.PLM` |
| 0x1 | u8[3] | pad |
| 0x4 | char[8] | model name (zero-padded, compared as two u32s — `COMPARE_FILENAMES`, types.h:95) |
| 0xC | u32 | modelHdr — placeholder on disc (kaitai calls it model_header_offset); runtime re-links by name via `LmHeader_ModelHeaderSearch` (bodyprog_80040B74.c:2307-2351) |

### s_IpdModelBuffer — 24 bytes each (ipd.h:131-146; ipd_reformat.c:81-116)

A "model buffer" = one spatial draw group inside the cell.

| off | size | field |
|-----|------|-------|
| 0x0 | u8 | modelInstanceCount |
| 0x1 | u8 | billboardCount (`field_1`) |
| 0x2 | u8 | subcellCount (visibility rects) |
| 0x3 | u8 | pad |
| 0x4 | s16 | minX (Q8, cell-relative) |
| 0x6 | s16 | maxX |
| 0x8 | s16 | minZ |
| 0xA | s16 | maxZ |
| 0xC | u32 | → s_IpdModelInstance[modelInstanceCount], stride **36** |
| 0x10 | u32 | → SVECTOR[billboardCount] billboard positions: {s16 vx,vy,vz (Q8, XZ cell-relative), s16 pad = billboard type 0/1} (Ipd_ChunkDraw:2524-2536 — type selects `Gfx_BillboardDraw(1|2, …)`, i.e. two vegetation sprite kinds) |
| 0x14 | u32 | → SVECTOR[subcellCount] visibility rects: {vx=minX, vy=maxX, vz=minZ, pad=maxZ} in Q7.8 cell-relative coords. If the sample point is inside a rect, the buffer's AABB (minX..maxZ above, Y fixed −8..+4 units) is frustum-tested and drawn (`Gfx_ChunkSubcellVisibleCheck`, bodyprog_80040B74.c:2546-2581) |

### s_IpdModelInstance — 36 bytes on disc (ipd_reformat.c:57-79)

| off | size | field |
|-----|------|-------|
| 0x00 | u32 | model index into modelInfo array (runtime replaces with pointer — `Ipd_HeaderModelBufferLinkObjectLists`, bodyprog_80040B74.c:2353-2371) |
| 0x04 | s16[3][3] | rotation matrix, Q12 (row-major m[r][c] at 4+(r*3+c)*2) |
| 0x16 | s16 | pad |
| 0x18 | s32[3] | translation t[0..2], **Q8**; X/Z relative to the cell's world corner (cellX·10240, cellZ·10240 added at draw — Ipd_ChunkDraw:2414-2415, 2516-2517), Y absolute |

This is the PSX 32-byte `MATRIX` (18B m + 2B pad + 12B t) preceded by the 4-byte model index.

## 2. IPD collision block (file offset 0x54, 308 bytes) — s_IpdCollisionData (ipd.h:83-111)

Collision **is inside the IPD**, self-contained per chunk. All offsets below are **relative to file offset 0x54** (`Ipd_CollisionPtrsInit` collision.c:179-188; `ParseIpdCollisionData` ipd_reformat.c:118-170). Sub-arrays live after the header (≥ 0x134 relative). Heights/coords Q7.8 or Q23.8 (256 = 1 unit).

| rel off | size | field |
|---------|------|-------|
| 0x00 | s32 | positionX (Q23.8) — world-space origin of collision-local coords; runtime shifts it by cell (`func_80044044`, bodyprog_80040B74.c:2373-2387) |
| 0x04 | s32 | positionZ (Q23.8) |
| 0x08 | u32 bitfield | splitVertexCount:8, surfaceCount:8, subcellCount:8, ptr18Count:8 |
| 0x0C | u32 | → splitVertices: SVECTOR3[splitVertexCount] (s16 x,y,z Q7.8); pairs define split lines inside subcells |
| 0x10 | u32 | → surfaces: s_IpdCollSurface[surfaceCount], 12 B (below) |
| 0x14 | u32 | → subcells: s_IpdCollSubcell[subcellCount], 10 B (below) |
| 0x18 | u32 | → ptr_18: s_IpdCollisionData_18[ptr18Count], 10 B (below) |
| 0x1C | s16 | subcellSize (Q7.8) — e.g. 512 = 2.0 units |
| 0x1E | u8 | subcellCountX (e.g. 20 → 20×2.0 = 40 = cell size) |
| 0x1F | u8 | subcellCountZ |
| 0x20 | u32 | → subcellRanges: s_IpdCollSubcellRange[countX*countZ **+ 1**] — grid, row-major `z*countX + x`; each {s16 field_0 = start into ptr_28, s16 field_2 = start into ptr_2C}; a cell's range is `[cell].field_0 .. [cell+1].field_0` (func_8006B1C8 collision.c:1292; func_8006CA18 collision.c:2274-2284). The +1 terminator entry is confirmed by size math in APU0000 (0x1A28−0x13E4 = 401 entries for 20×20) |
| 0x24 | u16 | field_24 = length of ptr_28 list |
| 0x26 | u16 | field_26 = length of ptr_2C list |
| 0x28 | u32 | → ptr_28: u8[field_24] — per-grid-cell lists of *subcell indices*; if index ≥ subcellCount it addresses `ptr_18[idx − subcellCount]` instead (collision.c:1294-1330, 2056-2062) |
| 0x2C | u32 | → ptr_2C: u8[field_26] — per-grid-cell lists of *surface indices* used for the ground-height pass (collision.c:2284-2313) |
| 0x30 | u8 | subcellCheckCount (runtime scratch) |
| 0x31 | u8[3] | pad |
| 0x34 | u8[256] | subcellCheckIdx — runtime dedup scratch, zeros on disc |

### s_IpdCollSurface — 12 bytes (ipd.h:27-47)
`{ q7_8 relX; q7_8 baseGroundHeight; q7_8 relZ; u16 bits(groundType:5 [e_GroundType, 12=None], disableHeight:3, field_6_8:3, field_6_11:4); q7_8 tiltAngleX; q7_8 tiltAngleZ }`.
Ground height at (x,z) = baseGroundHeight + tiltX·(x−relX) + tiltZ·(z−relZ) in collision-local coords (collision.c:2291-2300); final height compare in world Q8 with positionX/Z added (collision.c:2305-2306). "No ground" sentinel = 8.0 units (`Ipd_GroundHeightGet`, collision.c:2371-2381).

### s_IpdCollSubcell — 10 bytes (ipd.h:49-62)
`{ q7_8:14 x + u16:2 idA; q7_8:14 y + u16:2 idB; q7_8 z; u8 splitVertexIdx0, splitVertexIdx1; u8 surfaceIdx0, surfaceIdx1 }`. surfaceIdx 0xFF = none. The 2-bit idA/idB combine to a collision-trigger flag index `(idA*4)|idB` gating the subcell on event flags (func_8006B318, collision.c:1354-1357) — this is how puzzles enable/disable walls.

### s_IpdCollisionData_18 — 10 bytes (ipd.h:64-74)
`{ u16 bits(groundType:5, disableHeight:3, field_0_8:4, field_0_12:3, field_0_15:1); SVECTOR3 offset (Q7.8); q7_8 field_8 }` — point/cylinder-ish extra obstacles referenced from ptr_28 with idx ≥ subcellCount.

The exterior default (outside any IPD cell) is a flat plane: `Map_CollisionDataInit` zeroes everything and sets subcellSize=512 (bodyprog_80040B74.c:561-565); `Ipd_CollisionDataGet` (:2592-2663) returns the chunk's block when the queried cell has an IPD, NULL (= impassable "8 units down") if the cell has an IPD entry that isn't loaded, else the default.

## 3. LM format (embedded in IPD at lmHdrOff; standalone as .PLM)

**.PLM files ARE this format** — both the per-map `BG/*_GLB.PLM` ("global static models" shared across all chunks of a map) and `ITEM/*.PLM` item models. Verified headers: BG/APR_GLB.PLM and ITEM/AXE.PLM both start `30 06 00 ..`. `.ILM` (characters) is a different (skeletal) container; docs/File Formats.md:16-24 lists community templates for each.

All offsets in this section are relative to the **LM header base** (= lmHdrOff inside an IPD; = 0 in a .PLM file).

### LM header — 20 bytes on disc (lm.h:34-46; lm_reformat.c:99-181)

| off | size | field |
|-----|------|-------|
| 0x00 | u8 | magic = **0x30** ('0', `LM_HEADER_MAGIC`) |
| 0x01 | u8 | version = **6** |
| 0x02 | u8 | isLoaded (0 on disc) |
| 0x03 | u8 | materialCount |
| 0x04 | u32 | → s_Material[materialCount], stride 24 |
| 0x08 | u8 | modelCount (+3 pad) |
| 0x0C | u32 | → s_ModelHeader[modelCount], stride 16 |
| 0x10 | u32 | → u8 modelOrder[modelCount] |

### s_Material — 24 bytes (lm.h:10-32; lm_reformat.c:76-88)
`{ char name[8]; u32 texturePtr(0 on disc); u8 field_C; u8 unk_D; u8 field_E; u8 field_F; u16 field_10; u16 field_12; u16 field_14; u16 field_16 }` — on disc everything after name is normally 0. `name` is the TIM texture base name; the loader appends ".TIM" and streams it (`Material_TimFileNameGet` bodyprog_80055028.c:4169; `Texture_Get` :4072). Names ending in 'H' are "half-page" textures, others "full-page" (`LmFilter_IsHalfPage`, bodyprog_80040B74.c:2271-2286); the map keeps pools of 8 full-page + 2 half-page VRAM slots (terrain.h:46-54).

At load, `Material_FsImageApply` (bodyprog_80055028.c:1188-1218) writes: field_E = GPU tpage attribute byte; field_10 = PSX clut id `(clutY<<6)|(clutX>>4)`; field_14 = {u8 uBase = u·coeff (coeff 4/2/1 for 4/8/16bpp), u8 vBase}. field_F/field_12/field_16 hold the previous values for change detection.

### s_ModelHeader — 16 bytes (model.h:42-55; lm_reformat.c:47-74)
`{ char name[8]; u8 meshCount; u8 vertexOffset; u8 normalOffset; u8 bits(field_B_0:1 = use lit draw path, field_B_1:3 = OT-layer selector via func_800571D0 (bodyprog_80055028.c:1723-1746), field_B_4:2 = special draw mode for func_80059D50, unk:2); u32 → s_MeshHeader[meshCount], stride 24 }`. vertexOffset/normalOffset bias the scratch arrays so multiple meshes can be transformed together (func_8005759C, bodyprog_80055028.c:1865-1891).

### s_MeshHeader — 24 bytes (model.h:27-40; lm_reformat.c:34-45)

| off | size | field |
|-----|------|-------|
| 0x00 | u8 | primitiveCount |
| 0x01 | u8 | vertexCount |
| 0x02 | u8 | normalCount |
| 0x03 | u8 | lightingSlotCount (`unkCount_3`) |
| 0x04 | u32 | → s_Primitive[primitiveCount], 20 B each |
| 0x08 | u32 | → DVECTOR[vertexCount] vertex XY: {s16 x, s16 y}, Q8 model-local |
| 0x0C | u32 | → s16[vertexCount] vertex Z (Q8) — Z split out for GTE load efficiency (func_8005A900, bodyprog_80055028.c:3649-3682) |
| 0x10 | u32 | → s_Normal[normalCount]: {s8 nx,ny,nz; u8 count} (types.h:73-80). nx<<5 ≈ Q12; `count` = how many consecutive lighting slots this normal covers (sum of counts = lightingSlotCount) |
| 0x14 | u32 | → u8[lightingSlotCount] lighting slots (`unkPtr_14`): each byte is a **vertex index**; the per-frame relight pass reads it to fetch that vertex's position and overwrites the scratch copy with a computed brightness (func_80057658, bodyprog_80055028.c:1893-2025; flat variant func_80057A3C:2027-2069). Verified in APU0000: slot bytes are small ints < vertexCount |

Verified stride math in APU0000 mesh 0: 51 prims ×20, 99 verts ×4(XY)+×2(Z), 28 normals ×4, 125 slots — all section gaps match exactly.

### s_Primitive — 20 bytes (model.h:4-25) — the GPU packet source

| off | size | field | maps to |
|-----|------|-------|---------|
| 0x00 | u8,u8 | u0, v0 | POLY_GT4 u0/v0 (`*(s32*)&poly->u0 = *(s32*)&prim->field_0`, Gfx_MeshDraw bodyprog_80055028.c:2660) |
| 0x02 | u16 | clut (relative, see below) | POLY clut |
| 0x04 | u8,u8 | u1, v1 | POLY u1/v1 |
| 0x06 | u16 | bits: tpage:8 (low byte, `field_6_0`), materialIdx:7 signed (−1 = untextured → sentinel 32), isTransparent:1 (bit 15) | tpage word (masked `& 0xFFFFFF` :2661); bit15 → semi-trans: GT4 code `((flags>>15)*2)|0x3C`, GT3 `|0x34` (func_8005AC50 :4009, :3910) |
| 0x08 | u8,u8 | u2, v2 | POLY u2/v2 |
| 0x0A | u8,u8 | u3, v3 | POLY u3/v3 |
| 0x0C | u8[4] | vertex indices v0..v3 into the mesh vertex arrays | quad corners; **4th index == 0xFF ⇒ triangle** (GT3) in the lit path (func_8005AC50 :3845); map path treats 0xFF as repeat-first (bodyprog_80055028.c:3106-3111); triangles are ALSO commonly encoded as a repeated last index (APU0000 prim 0: verts 07 02 03 03) |
| 0x10 | u8[4] | lighting-slot indices n0..n3 into the mesh's slot array | per-corner shading (`field_2B8[...]`, e.g. :2419-2485) |

**Primitive types emitted:** every world primitive is a textured quad or tri. Depending on the map lighting mode (`g_WorldEnvWork.field_0`) and fog, Gfx_MeshDraw (bodyprog_80055028.c:2192-3236) emits POLY_GT4 (gouraud, per-corner colors from lighting slots × world tint × fog dpcs), an extra POLY_G4 fog overlay on PSX, or POLY_FT4 flat-tint (`__block19CC` :3092-3235, code 0x2C); the lit model path func_8005AC50 (:3765-4051) emits POLY_GT3/GT4. There are **no** per-vertex RGB colors in the file — colors are computed at runtime from: baked lighting slots + s_Normal, world tint (`g_WorldEnvWork.worldTintColor`), fog ramp, and point lights.

**UV/CLUT rebasing (critical for a writer):** on disc, prim `clut` and all UV bytes are *relative to the material's eventual VRAM placement*. After the material's TIM loads, `Model_MaterialFlagsApply` (bodyprog_80055028.c:1427-1469) patches every prim of that materialIdx in place: `field_6_0 = mat.field_E` (absolute tpage byte), `clut += (mat.field_10 − mat.field_12)`, `u/v bytes += (mat.field_14 − mat.field_16)` — since the disc's field_12/field_16 are 0, disc values are pure offsets (e.g. relative CLUT row index for multi-CLUT TIMs). A standalone renderer should compute the TIM's tpage/clut/u/v itself and add the disc-relative values.

## 4. Chunk streaming & world placement

- **File naming / grid:** an IPD's cell comes from its filename: `mapTag + XX + ZZ + ".IPD"` where XX/ZZ are 2-digit uppercase-hex **signed** s8 cellX/cellZ (`Map_MakeIpdGrid` bodyprog_80040B74.c:846-895, `ConvertHexToS8` :897-940). E.g. APU0000 = (0,0), APUFFFE = (−1,−2), THR05FD = (5,−3). Tags come from `MAP_INFOS` (src/bodyprog/sys/map_info.c:468-485): THR/SPR/SPU/RSR/RSU/APR/APU/DR/DRU are exteriors with a `FILE_BG_*_GLB_PLM`; SC/SU/ER/HP/HU are interiors (no global PLM). Grid storage: `s_ChunkColumn chunkGrid[19]` of 16 s16 file indices, center at [8].idx[8]; valid X ∈ [−8,7], Z ∈ [−8,10] (terrain.h:33-38,73-74; :855-863). Files are located via the file table (`g_FileTable`, `FileType_Ipd = 6`, include/main/fileinfo.h:26-40).
- **Buffers:** `Map_Init(GLOBAL_LM_BUFFER, IPD_BUFFER, 0x2C000)` (world_draw.c:117). The 0x2C000 (180224 B) buffer is sliced by the map's active chunk count — exteriors 4 slices (45 KB/chunk), interiors 1–2 (`Ipd_PlayerChunkInit` world_draw.c:178-241 reading `MapFlag_OneActiveChunk/TwoActiveChunks/Interior`, map.h:14-21; slicing in `Ipd_ActiveChunksClear` bodyprog_80040B74.c:726-844). So max on-disc IPD size ≈ slice size.
- **Load policy:** each frame `Ipd_CloseRangeChunksInit` (world_draw.c:280-408) computes two sample points (player + look-ahead) and calls `Ipd_ChunkInit` → `Map_ChunkLoad` (bodyprog_80040B74.c:1376-1524): scans a ±1 cell window (PSX; interiors only load the exact cell), loads any missing IPD whose padded edge distance ≤ 0 via `Ipd_LoadStart` (:1904-1919, a raw `Fs_QueueStartRead` of the whole file into the slot). Eviction picks the slot with most material load cost / farthest edge distance (`Ipd_FreeChunkFind` :1822-1902). After load completes, `IpdHeader_FixOffsets` (:2165-2233) relocates pointers, loads material TIMs, and name-links models (chunk-local LM first, then global PLM).
- **Draw:** `Ipd_ChunkCheckDraw` (:2014-2104) walks active chunks; exteriors draw all loaded chunks, interiors only the player's cell (PSX `Ipd_CellPositionMatchCheck` :2106-2143). `Ipd_ChunkDraw` (:2389-2544) computes the viewer's 5×5 subcell, reads the header's draw table pair {start,count}, iterates `modelOrderList` → modelBuffers → per-buffer visibility rects + AABB frustum test → per-instance matrix (t[0]/t[2] += cell corner) → `func_80057090` (bodyprog_80055028.c:1677-1721) → mesh transform + `Gfx_MeshDraw`, plus billboards.
- OT bucketing: prim depth = max corner SZ, OT index `(depth >> interlaceShift) >> 2`, depth clamp 32..fog-far (Gfx_MeshDraw :2560-2592).

## 5. Existing tooling in/near the repo

- **pc_port/src/ipd_reformat.c / lm_reformat.c** — complete byte-level parsers (this report's primary source).
- **tools/kaitai_scripts/ipd.ksy** — Kaitai spec covering IPD + LM + primitives + collision (matches the C code; its collision instance offsets carry "TODO wrong offset" notes because they're relative to +0x54, and the `subcell_ranges` repeat-expr is wrong — use countX*countZ+1).
- **tools/silentassets/extract.py** — unpacks the `SILENT.`/`HILL.` disc containers using the executable's file table (the raw extraction that produced `C:/Claude/silenthill/disc_extract/`).
- **docs/File Formats.md** — format index; external references: Sparagas `sh1_model.bt` (010 template for IPD/PLM/ILM) and belek666 `sh_ipd2obj` (IPD→OBJ converter; the ipd.h comments reference it for collision field sizes).
- **pc_port/tools/extract_map_data.py** — extracts *code-overlay data* (cutscene tables) from VIN/MAP*.BIN, not geometry. **tools/maptool.py** — compares map overlay code, and can list map-header spawns; not geometry.
- `C:/Claude/silenthill/SHModelViewer` (native, TMD-only) and `C:/Claude/silenthill/modelviewer` (Python TMD/ANM via silent-hill-museum) — neither parses IPD/PLM yet.
- Raw data: `disc_extract/BG/*.IPD` + `*_GLB.PLM` + `*.TIM` (map), `disc_extract/ITEM/*.PLM`, `disc_extract/TEST/BTT_*.IPD` (test map). VIN/MAP*_S*.BIN are code overlays (events/cameras/collision triggers/spawns — see s_MapOverlayHdr, include/bodyprog/map/map.h:403-528), not geometry; a level editor will eventually need them for entities, but geometry+collision is fully inside IPD/PLM.

## 6. Parser checklist (minimum viable)

1. Read header (0x00–0x53); validate magic 0x14.
2. Parse modelInfo[16·n] at modelInfoOff, modelBuffers[24·n] at modelBuffersOff (+ their instance/billboard/rect arrays via file-relative offsets), modelOrderList.
3. Parse collision at 0x54 with offsets rebased +0x54; array counts from the 0x08 bitfield + field_24/field_26 + (countX·countZ+1) ranges.
4. At lmHdrOff parse LM (magic 0x30 v6): materials[24·n], modelHeaders[16·n] → meshHeaders[24·n] → prim/vertexXY/vertexZ/normal/lightingSlot arrays (all offsets relative to lmHdrOff).
5. Geometry per prim: quad (or tri if idx3==0xFF or idx3==idx2/idx0), positions = (xy[i].x, xy[i].y, z[i]) Q8 in instance space; world = instanceMatrix(Q12 rot, Q8 trans) + (cellX·10240, 0, cellZ·10240).
6. Textures: material name + ".TIM" in the same BG dir; disc UV/clut are offsets to add to the TIM's own placement.

## Key files

- C:\Claude\silenthill\silent-hill-decomp\include\bodyprog\formats\ipd.h — In-memory s_IpdHeader / s_IpdModelInfo / s_IpdModelBuffer / s_IpdModelInstance / all collision structs (s_IpdCollisionData, s_IpdCollSurface, s_IpdCollSubcell, s_IpdCollisionData_18, s_IpdCollSubcellRange) + e_GroundType
- C:\Claude\silenthill\silent-hill-decomp\include\bodyprog\formats\lm.h — s_LmHeader, s_Material, s_GlobalLm; LM magic '0' (0x30), version 6 — PLM files and IPD-embedded geometry are this format
- C:\Claude\silenthill\silent-hill-decomp\include\bodyprog\formats\model.h — s_ModelHeader, s_MeshHeader, s_Primitive (20-byte quad/tri packet)
- C:\Claude\silenthill\silent-hill-decomp\include\decomp\types.h — s_Normal (s8 nx,ny,nz + u8 count), DVECTOR/SVECTOR3, u_Filename
- C:\Claude\silenthill\silent-hill-decomp\pc_port\src\ipd_reformat.c — Byte-accurate C parser of the on-disc 32-bit IPD layout (best single reference for a Python parser)
- C:\Claude\silenthill\silent-hill-decomp\pc_port\src\lm_reformat.c — Byte-accurate C parser of on-disc LM/PLM layout (materials, model headers, mesh headers)
- C:\Claude\silenthill\silent-hill-decomp\tools\kaitai_scripts\ipd.ksy — Kaitai spec for IPD + embedded LM/PLM + primitives + collision (community-verified byte layout)
- C:\Claude\silenthill\silent-hill-decomp\src\bodyprog\gfx\bodyprog_80040B74.c — All Ipd_* runtime: FixOffsets (relocation = file offsets), chunk grid, streaming, Ipd_ChunkDraw, subcell draw table, material->prim patching, Map_MakeIpdGrid filename convention
- C:\Claude\silenthill\silent-hill-decomp\src\bodyprog\gfx\bodyprog_80055028.c — Mesh/primitive drawing: Gfx_MeshDraw, func_8005AC50 (GT3/GT4, 0xFF tri sentinel), vertex/normal transform funcs, LmHeader_FixOffsets, Material_FsImageApply, Model_MaterialFlagsApply (UV/CLUT rebasing)
- C:\Claude\silenthill\silent-hill-decomp\src\bodyprog\collision\collision.c — Collision consumption: Ipd_CollisionPtrsInit (offset base), subcell grid lookup, surface height math, func_8006B318 subcell semantics
- C:\Claude\silenthill\silent-hill-decomp\src\bodyprog\gfx\world_draw.c — Map_Init(0x2C000 buffer), Ipd_PlayerChunkInit, Ipd_CloseRangeChunksInit (streaming sample points), Gfx_InGameDraw
- C:\Claude\silenthill\silent-hill-decomp\include\bodyprog\map\terrain.h — s_MapTerrain, s_Chunk, chunk grid (19x16), chunk texture pools
- C:\Claude\silenthill\silent-hill-decomp\src\bodyprog\sys\map_info.c — MAP_INFOS: map tag -> GLB.PLM file + interior/exterior + active chunk count
- C:\Claude\silenthill\silent-hill-decomp\docs\File Formats.md — Community format doc index; links to Sparagas sh1_model.bt and belek666 sh_ipd2obj external tools
- C:\Claude\silenthill\silent-hill-decomp\tools\silentassets\extract.py — Extracts files from SILENT./HILL. disc containers using the file table
- C:\Claude\silenthill\disc_extract\BG — All retail map geometry: *.IPD chunks (tag+hexcell naming), *_GLB.PLM global models, *.TIM textures

## Open questions

- s_Primitive.field_6 low byte (tpage attribute) on disc is 0 in samples and is overwritten at material-load time — confirm whether any IPD ships nonzero initial tpage bytes (would matter for a writer).
- unkPtr_14 lighting-slot bytes: confirmed used as VERTEX INDICES by the point-light path (func_80057658 reads scratch field_2B8 values as vertex indices), but the field_0==0 draw path (__block1530, bodyprog_80055028.c:3010) reads the same bytes as darkness values (0x1000 - v*32). Which maps run in mode 0 and whether those IPDs bake brightness instead of indices is unverified.
- s_IpdCollisionData_18 (ptr_18) records: consumed by func_8006C3D4/func_8006C45C as point/cylinder-like obstacles; exact geometric meaning of offset/field_8 not fully pinned down.
- s_IpdCollSubcell field_0_14/field_2_14 2-bit IDs combine into a collision-trigger flag index ((a*4)|b) — the authoring meaning (which flag group a subcell belongs to) needs a map-side survey.
- s_Material.field_C exact semantics (1 = 'texture externally applied / skip pool load'); unk_D unknown.
- IPD header bytes 0x0B and 0x0C..0x13 (9 bytes): always 0 in samples, preserved blindly by the PC reformatter; unknown purpose.
- LM header modelOrder array (u8 per model) exists in both PLM and IPD-embedded LM; its consumer besides logging was not located (IPD draws use the separate per-subcell modelOrderList instead).
- Whether IPD collision subcellRanges always has exactly countX*countZ+1 entries (sample math says yes: 401 entries for 20x20) — verify across all files before writing a re-packer.
- Mesh vertexCount can exceed 90 (sample: 99) while s_GteScratchData.screenXy_0 is declared [90] with overlapping following fields — PSX scratchpad aliasing; a parser should trust the counts, not the C array sizes.
