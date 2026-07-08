# Research: disc-inventory

## Summary

disc_extract/ holds 493 .IPD level-geometry chunks (all in BG/), named `<AREA_TAG><XX><ZZ>.IPD` with two signed-hex-byte cell coordinates, grouped into 13 area tags that map many-to-one onto the 43 mapX_sYY DLLs via the MAP_INFOS table in src/bodyprog/sys/map_info.c:468-485. Texture binding is by 8-char TIM basenames embedded in IPD/PLM material records (Material_TimFileNameGet, bodyprog_80055028.c:4169), not by filename convention. Best first test maps: (1) DRU — otherworld sewer, map6_s03, only 6 IPD chunks + 1 PLM + 12 TIMs (~586 KB total); (2) HP — fog-world hospital, map3_s00/s01/s06, the smallest MapFlag_Interior area at 20 IPD chunks + 31 TIMs (~1.5 MB). SILENT (80,476,160 B) and HILL (520,007,616 B) at the root are the original packed disc containers; the file table lives in the executable (SLUS_007.07, 81,920 B). TEST/BTT_*.IPD (2,560 B each) are ultra-minimal unused IPDs useful as parser fixtures.

# disc_extract Asset Inventory + First Test Map Candidates

## 1. Directory structure and file counts

`C:/Claude/silenthill/disc_extract/` (counts by dir\extension, from recursive listing):

| Dir | Contents |
|---|---|
| `1ST/` | 10 .TIM, 2 .BIN (BODYPROG.BIN 674,560 B engine overlay; B_KONAMI.BIN 4,096 B), 2 .VAB (BASE.VAB, COATION.VAB) — boot/engine, fonts, error screens |
| `ANIM/` | 113 .ANM (character animations), 44 .DMS (cutscene keyframe files, per location, e.g. HP1F03.DMS 2,816 B, LAST4.DMS 24,832 B) |
| `BG/` | **493 .IPD** (level geometry chunks), 694 .TIM (level textures), 11 .PLM (per-area global models: `<TAG>_GLB.PLM` + MGR.PLM + BG_ITEM.PLM), 2 .BIN (HP_SAFE1.BIN / S__SAFE2.BIN 2,372 B each = encrypted anti-modchip overlays, NOT level data — decomp `docs/Game Information.md:10`) |
| `CHARA/` | 49 .ILM (skeletal models), 46 .TIM (character textures) |
| `ITEM/` | 87 .TMD (item-screen models), 17 .PLM, 23 .TIM (+1 stray .py helper) |
| `MISC/` | 32 .DAT (DEMO0000.DAT… — attract-demo input recordings, 2,048 B each) |
| `SND/` | 40 .KDT (Konami MIDI), 90 .VAB (sample banks), 1 .wav |
| `TEST/` | 5 .IPD, 5 .CMP (+.dec), 2 .DMS, 2 .ILM, 16 .TIM, 3 .TMD — ITF leftovers, unused by game |
| `TIM/` | 207 .TIM (full-screen images) (+ stray extracted_pngs/, HEROPIC2_pngs/, TITLE_E_test_tims/ working dirs from prior sessions) |
| `VIN/` | 49 .BIN — map/screen overlay code: MAP0_S00.BIN…MAP7_S03.BIN (43 real maps; MAPT_S00.BIN and MAPX_S00.BIN are 0 bytes), plus OPTION/SAVELOAD/STF_ROLL/STREAM.BIN |
| `XA/` | 32 files (30 extensionless XA/FMV banks, e.g. Z1_16180 37.8 MB, + one .bin/.xa duplicate pair) |
| root | SILENT, HILL, SLUS_007.07, SYSTEM.CNF, filetable.c.inc (194,787 B), fileenum.h.inc (104,280 B), plus vgmstream tooling (vgmstream-cli.exe, 11 DLLs, COPYING) and 117 snd_map*.wav conversions |

NOTE: `disc_extract/README.md` and `USAGE.md` are **vgmstream audio-tool docs**, not asset docs. The authoritative format doc is `C:/Claude/silenthill/silent-hill-decomp/docs/File Formats.md`.

## 2. IPD naming convention and map identifier mapping

### Naming convention (confirmed in engine code)
IPD name = `<AREA_TAG><XX><ZZ>.IPD` where XX and ZZ are **signed hex bytes** = world-grid cell X and Z. Definitive parser: `Map_MakeIpdGrid` at `C:/Claude/silenthill/silent-hill-decomp/src/bodyprog/gfx/bodyprog_80040B74.c:846-895` — scans the whole file table for `FileType_Ipd` entries whose name starts with the map tag (line 872), then `ConvertHexToS8` (line 897) parses chars [0..1]→X and [2..3]→Z (lines 875-879) into a grid spanning x −8..7, z −8..10 (lines 857-863). So `DRUFF01.IPD` = area DRU, cell (−1, 1); `HP00FE.IPD` = area HP, cell (0, −2). The active map's tag/PLM/chunk-count come from `Ipd_MapFileInfoSet(mapInfo->tag, mapInfo->plmFileIdx, …)` called at `src/bodyprog/gfx/world_draw.c:233` (impl at bodyprog_80040B74.c:668).

### Area tags → IPD counts → map DLLs
Area table `MAP_INFOS` at `src/bodyprog/sys/map_info.c:468-485` (fields: global PLM file, tag string, flags); `e_MapType` at `include/bodyprog/map/map.h:87-107`; per-map assignment read from every `src/maps/*/mapX_sYY_header.c` (`.mapInfo = &MAP_INFOS[MapType_*]`):

| Tag | IPDs | GLB PLM (size) | Flags | Map DLLs (src/maps/… ↔ VIN/MAPx_Syy.BIN) | Likely locale |
|---|---|---|---|---|---|
| THR | 128 | THR_GLB.PLM (40,704) | 4-chunk exterior | map0_s00, map0_s01, map2_s00, map2_s03 | town streets |
| SC | 42 | none (NO_VALUE) | 2-chunk **Interior** | map1_s00, map1_s01, map1_s06 | school (normal) |
| SU | 40 | none | 2-chunk **Interior** | map1_s02, map1_s03, map1_s04, map1_s05 | school (otherworld) |
| SPR | 32 | SPR_GLB.PLM (40,960) | 4-chunk exterior | map2_s02, map4_s00, map4_s06 | commercial district (normal) |
| SPU | 33 | SPU_GLB.PLM (39,424) | 4-chunk exterior | map4_s02, map4_s03, map4_s05 | commercial district (otherworld) |
| RSR | 27 | RSR_GLB.PLM (39,936) | 4-chunk exterior | map5_s01 | lakeside resort |
| RSU | 23 | RSU_GLB.PLM (40,192) | 4-chunk exterior | map6_s00, map6_s02 | resort (otherworld) |
| APR | 0 | APR_GLB.PLM (40,704) | unused (`MapType_APR` @unused, map.h:96) | — | amusement park normal (cut) |
| APU | 9 | APU_GLB.PLM (14,080) | 4-chunk exterior | map6_s04, map6_s05 | amusement park (otherworld) |
| ER / ER2 | 58 (shared tag "ER", map_info.c:478-479) | none | 2-chunk **Interior** | ER: map0_s02, map2_s01, map2_s04, map4_s01, map5_s02, map5_s03, map6_s01; ER2: map7_s00–map7_s03 | misc interior rooms (cafe, church, motel, boat, Nowhere) |
| DR | 17 | DR_GLB.PLM (33,024) | 4-chunk + water zones | map5_s00 | sewers |
| DRU | 6 | DRU_GLB.PLM (19,456) | 4-chunk + water zones | map6_s03 | sewers (otherworld) |
| HP | 20 | none | 2-chunk **Interior** | map3_s00, map3_s01, map3_s06 | hospital (fog world) |
| HU | 58 | none | 2-chunk **Interior** | map3_s02, map3_s03, map3_s04, map3_s05, map4_s04 | hospital (otherworld) |

(map2_s01 and map5_s03 use raw `&MAP_INFOS[9]` = ER: `src/maps/map2_s01/map2_s01_header.c:33`, `src/maps/map5_s03/map5_s03_header.c:37`.)

Total: 493 IPDs. Key implication for the editor: **a "map" (DLL) is game logic; level geometry is owned by the AREA tag** — several map DLLs render the same IPD chunk set. Map DLLs are built one-per-`src/maps/<name>` dir via `add_library(${MAP_NAME} SHARED …)` at `pc_port/maps/CMakeLists.txt:36-61`.

### Texture binding (critical for editor)
Level TIMs are NOT found by naming convention. Each IPD/PLM **material record embeds an 8-char TIM basename**; the engine appends "TIM" and resolves it by name against the file table: `Material_TimFileNameGet` at `src/bodyprog/gfx/bodyprog_80055028.c:4169-4185`, used by `func_800566B4` at :1220-1255 (`Fs_FindNextFile(filename, …)` → `Fs_QueueStartReadTim`). Exterior per-chunk TIMs (e.g. THR0000-style) correlate with cells; interior TIMs use room-style names (HP1F011 = hospital 1F room 01 sheet 1, `…H` suffix = otherworld/half variants).

## 3. First test map candidates

### Candidate A (recommended smoke test): DRU — otherworld sewer, map DLL `map6_s03`
Smallest chunk count in the game (6 IPDs). Engine-wise "exterior" (4-active-chunk streaming + WATER_LIGHT_ZONES_1, map_info.c:481) but visually enclosed tunnels. Header: `src/maps/map6_s03/map6_s03_header.c:32`.

Complete asset set (all in `disc_extract/BG/` unless noted; bytes):
- IPD (6, total 202,240): DRU0000.IPD 31,744 (0,0); DRU0001.IPD 37,888 (0,1); DRU0100.IPD 36,864 (1,0); DRU0200.IPD 33,536 (2,0); DRUFF00.IPD 26,368 (−1,0); DRUFF01.IPD 35,840 (−1,1) — footprint x −1..2, z 0..1
- PLM: DRU_GLB.PLM 19,456
- TIM (12, total 364,032): DRU01F 33,024; DRU02F 33,024; DRU02H 16,640; DRU03F 33,024; DRU04F 33,024; DRU05F 33,024; DRU05H 16,640; DRU06F 33,024; DRUG01 33,280; DRUG02 33,280; DRUG03 33,024; DRUG04 33,024
- Overlay/logic: VIN/MAP6_S03.BIN 92,928 ↔ `src/maps/map6_s03/` DLL
- Total geometry+texture payload ≈ 586 KB

### Candidate B (recommended first real interior): HP — fog-world hospital, map DLLs `map3_s00` / `map3_s01` / `map3_s06`
Smallest `MapFlag_Interior` area (20 IPDs vs SU 40 / SC 42 / ER,HU 58). No global PLM (map_info.c:482). Header: `src/maps/map3_s00/map3_s00_header.c:31`.

Complete asset set (bytes):
- IPD (20, total 557,568): HP0000 39,680; HP0001 48,640; HP0002 45,056; HP0003 47,104; HP00FE 8,448; HP00FF 11,008; HP0100 13,056; HP0101 42,752; HP0102 22,016; HP01FF 33,280; HP0200 10,752; HP0201 39,936; HP0202 57,344; HP02FF 10,240; HP0300 36,352; HP0301 6,656; HP0302 30,720; HP03FF 17,664; HPFF00 18,944; HPFFFF 17,920 — footprint x −1..3, z −2..3
- TIM (31, total 972,800): HP1F011 33,280; HP1F012 33,536; HP1F01H 16,640; HP1F021/022 33,280 ea; HP1F031/032 33,280 ea; HP1F03H 8,448; HP1F041/042 33,280 ea; HP1F071 33,280; HP1F072 33,024; HP1F081/082 33,280 ea; HP1F091/092 33,280 ea; HP1F101/102 33,280 ea; HP1F111 33,280; HP1F121 33,280; HP1F122 33,024; HP1F131/132 33,280 ea; HP2F011/012 33,280 ea; HPB1011 33,280; HPB1021 33,280; HPB1022 33,024; HPB1041 33,280; HPB1042 33,024; HPB104H 16,640
- Cutscene: ANIM/HP1F03.DMS 2,816 (loaded by `src/maps/map3_s00/map3_s00_2.c:109`)
- Overlays: VIN/MAP3_S00.BIN 51,456; MAP3_S01.BIN 62,208; MAP3_S06.BIN 51,968
- (BG/HP_SAFE1.BIN 2,372 is anti-modchip code, exclude)
- Total geometry+texture payload ≈ 1.5 MB

### Bonus fixture: TEST/BTT_*.IPD
Unused test map "BTT_": BTT_0000/BTT_00FF/BTT_FF00/BTT_FFFF.IPD — **2,560 B each**, 4 cells around origin, plus RMT0000.IPD 24,064. Ideal first bytes for an IPD parser unit test (caveat: ITF-era leftovers, format version vs retail unverified; game never loads them — MAPT_S00.BIN/MAPX_S00.BIN are 0 bytes, `include/bodyprog/map/map.h:80-81`).

## 4. Format one-liners (from `silent-hill-decomp/docs/File Formats.md:14-29`)
- **.IPD** — "Local static models": per-cell level geometry chunks; parsers: Sparagas sh1_model.bt, belek666 sh_ipd2obj (File Formats.md:22)
- **.PLM** — "Global static models": area-wide shared geometry/material set (`<TAG>_GLB.PLM`) (:24)
- **.ILM** — skeletal character models (:21)
- **.ANM** — character animation data (museum sh1anm.ksy) (:16)
- **.DMS** — cutscene keyframe data; local template `docs/file_formats/sh1_dms.bt` (:20)
- **.KDT** — Konami MIDI tracker music (Nisto kdt-tool) (:23)
- **.CMP** — LZSS-compressed data, unused by game; decompressor `src/screens/b_konami/lzss.c` (:18)
- **.DAT** — attract-demo playback: per-frame button states (:19)
- **.TIM/.TMD/.VAB** — standard PsyQ texture / 3D model (item screen only) / audio bank (:25-27)

## 5. SILENT / HILL root files
Yes — these are the two packed disc containers the extraction came from (`docs/File Formats.md:31-36`): **SILENT = 80,476,160 B** (~76.7 MiB, all data/overlay files incl. every BG/ANIM/CHARA/etc. entry) and **HILL = 520,007,616 B** (~495.9 MiB, XA audio + FMV). They have **no internal file table**; the table is embedded (transformed) in the executable **SLUS_007.07 (81,920 B)** — decomp copy `src/main/filetable.c.USA.inc`, extract-side copies `disc_extract/filetable.c.inc` + `fileenum.h.inc` (enum e.g. `FILE_BG_APU0000_IPD = 174` at fileenum.h.inc:176). Extraction tool: `silent-hill-decomp/tools/silentassets/extract.py`. Files are addressed by table index → disc sector; the editor can either read loose extracted files or reuse that table for repacking.

## Key files

- C:/Claude/silenthill/disc_extract/BG — All 493 .IPD level chunks + 694 level TIMs + 11 global PLMs; the level editor's primary asset source
- C:/Claude/silenthill/silent-hill-decomp/src/bodyprog/gfx/bodyprog_80040B74.c — Map_MakeIpdGrid (:846-895) + ConvertHexToS8 (:897) — definitive IPD filename→grid-cell convention; Ipd_MapFileInfoSet (:668)
- C:/Claude/silenthill/silent-hill-decomp/src/bodyprog/sys/map_info.c — MAP_INFOS[16] (:468-485) — area tag, global PLM file, interior/exterior flags per MapType
- C:/Claude/silenthill/silent-hill-decomp/include/bodyprog/map/map.h — e_MapIdx (:34-82) and e_MapType (:87-107) enums; grid/flag types
- C:/Claude/silenthill/silent-hill-decomp/src/bodyprog/gfx/bodyprog_80055028.c — Material_TimFileNameGet (:4169-4185) + func_800566B4 (:1220-1255) — TIM texture names embedded in IPD/PLM materials, resolved by file-table name lookup
- C:/Claude/silenthill/silent-hill-decomp/docs/File Formats.md — Authoritative per-extension format table (:14-29), SILENT/HILL container layout (:31-36), folder purposes (:44-56)
- C:/Claude/silenthill/disc_extract/fileenum.h.inc — Full file-index enum (FILE_BG_*_IPD etc.) matching the in-exe file table; needed for repacking/indexing
- C:/Claude/silenthill/silent-hill-decomp/pc_port/maps/CMakeLists.txt — One DLL per src/maps/<mapX_sYY> dir (:36-61) — the map-DLL ↔ disc-overlay mapping
- C:/Claude/silenthill/disc_extract/TEST — BTT_*.IPD 2,560-byte unused test chunks — smallest possible IPD parser fixtures (retail-format compatibility unverified)

## Open questions

- Do interior areas (HP/SC/SU/ER/HU) place IPD cells on the same world-grid scale as exteriors, and what is the world-unit size of one cell (needed for editor coordinate mapping)?
- MapType_ER vs MapType_ER2 rows in MAP_INFOS look identical (same "ER" tag, map_info.c:478-479) — what actually differs (chunk buffer slicing? speed zones elsewhere in struct)?
- Are the TEST/BTT_*.IPD files the same IPD format version as retail BG/ IPDs, or an earlier ITF variant (needs header magic comparison before using as parser fixtures)?
- Interior TIM streaming: which code path loads room TIMs (HP1F011 etc.) at room transitions — purely via material-name lookup in func_800566B4, or is there an additional per-room preload table in the map overlay?
- Collision data location: IPD is described as static models — does it also embed the collision/floor data the editor must edit, or does collision live in the VIN map overlay (.BIN) data tables?
