# Research: existing-tooling

## Summary

Two in-house viewers exist and split cleanly: SHModelViewer (C11, CMake/MSYS2, 389-line main.c, builds and runs) renders TMDs through the port's real libgs_stub.c GS pipeline and is a fidelity-reference/preview harness rather than a parser library; modelviewer/ is a Python toolkit with clean standalone TMD and ANM parsers plus a vendored silent-hill-museum (three.js + Kaitai .ksy specs). The strongest lift-candidates for level-editor converters are pc_port/tools/tim_convert.py (full TIM<->PNG codec), tools/kaitai_scripts/ipd.ksy (608-line full IPD spec incl. collision), include/bodyprog/formats/*.h (canonical C structs for IPD/LM/model/TMD — directly compilable in C++ tooling), and tools/silentassets/extract.py + insertovl.py (container read AND write-back). extract_map_data.py reads PSX map-overlay BINs + symbol maps and emits C initializer files; it is decomp-glue, not a general map parser. Toolchain: Python 3.14.3 + Pillow 12.2.0, VS2022 Community with cl.exe 14.44, CMake 4.3.1, Ninja 1.13.2, MinGW GCC 13.1, C:\vcpkg bootstrapped — but Qt is NOT installed, which is the single blocker for building TrenchBroom (already forked and checked out at C:/Claude/silenthill/trenchbroom, branch sh1-editor, requires Qt 6.10 per its BUILD.md).

# In-house Tooling Reuse Assessment for SH1 Level Editor

## 1. SHModelViewer (C:/Claude/silenthill/SHModelViewer/)

**Language/build**: C11 (single TU), CMake >= 3.16 + Ninja under MSYS2 MINGW64 (same toolchain as the port). Built exe exists: `SHModelViewer/build/shmodelviewer.exe`. CMakeLists (`SHModelViewer/CMakeLists.txt:14-24`) points at the decomp tree via `SH_DECOMP` cache var and reuses two things unmodified: PsyCross (`add_subdirectory`, line 27) and `pc_port/src/stubs/libgs_stub.c` compiled straight in (lines 38-41). Links `psycross_static` + SDL2 + opengl32.

**Structure**: one file, `SHModelViewer/src/main.c` (389 lines). It is deliberately NOT a parser library — it feeds the raw TMD file to the port's own renderer.

**Formats parsed**: TMD only. No TIM (VRAM is filled all-white as a stand-in, `main.c:277-282`), no IPD, no DMS, no ILM/ANM (explicitly listed as "not yet" in `SHModelViewer/README.md`).

**TMD-touching code (file:line)**:
- `src/main.c:97-117` `compute_radius()` — walks the on-disk TMD object table (7 u32 per object, offsets relative to object table) to find bounding radius.
- `src/main.c:130-170` `preprocess_tmd_flags()` — the most valuable format knowledge in the file: documents TMD prim packet sizes (untextured F3=16/G3=20/F4=20/G4=24; textured TF3=24/TG3=28/TF4=32/TG4=36; no-light NG3=24/NF4=16/NG4=28), the mode-byte bit decode (`qd=(mode>>3)&1, iip=(mode>>4)&1, tme=(mode>>2)&1`), and the PSX lit-flag inversion (bit0==0 means LIGHT ON) vs the port's dispatch.
- `src/main.c:174-207` `scene_init()` — TMD header layout (word0 id=0x41, word1 flags, word2 nobj) and hookup via `GsMapModelingData`/`GsGetTMDObject`/`GsLinkObject4_PC`.
- `src/main.c:254` TMD magic validation (`id != 0x41` reject).

**Rendering approach**: exact port pipeline — `GsMapModelingData` -> `GsSortObject4J` -> `GsTMDfast*` -> `addPrim` -> `GsDrawOt`, all implemented in `pc_port/src/stubs/libgs_stub.c` (1589 lines): GsTMDfast* handler prototypes at `libgs_stub.c:104-119`, GsFCALL4 dispatch table population at `libgs_stub.c:139-163`, `GsGetTMDObject` at `libgs_stub.c:329`, headless screenshot `SH_TakeScreenshot` at `libgs_stub.c:21`. `--shot out.bmp` renders 8 frames headless and writes a BMP (`main.c:246-249, 378-382`) — useful for automated visual regression of converters.

**Code quality**: high — heavily commented with format/ABI rationale, isolated from game tree, no globals leakage beyond libgs externs. But it is a *harness*, not a converter: the only liftable parsing is `preprocess_tmd_flags`'s packet-size table. Its real reuse value for the editor is (a) a pixel-faithful preview window driven by the port's renderer, (b) a template for standalone tools that link libgs_stub + PsyCross.

## 2. modelviewer/ (C:/Claude/silenthill/modelviewer/) — DIFFERENT project

Python toolkit + vendored checkout of **silent-hill-museum** (TypeScript/three.js web viewer). Per `modelviewer/README.md`: museum is the modding/conversion workbench; SHModelViewer is the port-fidelity reference.

- `modelviewer/formats/tmd.py` (147 lines) — clean standalone TMD parser: header doc at lines 1-27 (object table sizeof 0x1C, relative-vs-absolute offsets per flags bit0), `parse()` at line 73, `load()` at line 145. Dataclasses TmdVertex/TmdPrimitive/TmdObject. **Direct lift for a Python TMD->OBJ/glTF converter.**
- `modelviewer/formats/anm.py` (134 lines) — ANM parser: `parse()` at line 70, `get_bone_world_transform()` at line 119. ANM header layout also documented in `modelviewer/README.md` (12-byte header: num_rotations, num_translations, frame_size = nr*9+nt*3, num_bones, flags, end_offset).
- `modelviewer/viewer.py` (354 lines) — pygame + PyOpenGL wireframe TMD viewer with ANM keyframe scrubbing; deps `pygame>=2.5, PyOpenGL>=3.1, numpy>=1.24` (`requirements.txt`).
- `modelviewer/convert_animinfo.py` (191 lines) — museum's `src/sh1/sh1-animinfo.ts` -> PC-port C `s_AnimInfo` arrays.
- `modelviewer/silent-hill-museum/ksy/` — Kaitai specs: `sh1anm.ksy`, `ilm.ksy`, `psx_tim.ksy`, `anm.ksy`, `mdl.ksy`, `dds.ksy` (SH1 ILM + TIM machine-readable specs). `src/sh1/sh1.ts` + `sh1-animinfo.ts` = working ILM/skeleton/anim implementation (TypeScript reference).

## 3. Python tooling inventory

### silent-hill-decomp/pc_port/tools/ (all paths under C:/Claude/silenthill/silent-hill-decomp/pc_port/tools/)

- **`extract_map_data.py`** (1313 lines) — THE map-data extraction pipeline, but for decomp glue, not editor geometry. Reads `configs/USA/maps/sym.map*.txt` (symbol->address tables, parser `parse_sym_file` at line 613) + `disc_extract/VIN/MAP*.BIN` (original PSX map overlay binaries); emits `pc_port/build_gen/extracted_data/{map}_data.c` — one C file per map of static initializers for symbols whose data lives only in the PSX binary (voice cmd tables, cutscene timers/cameras, world-object pose arrays, romper scalars, TIM file-idx tables). Key internals: TARGETS symbol->type table from line 30; size inference `infer_size` line 650; emitters `fmt_array` 663, `emit_vector3` 684, `emit_world_object_pose_array` 690, PSX->PC pointer-relocating world-object emitter `emit_world_object` 818 with mirror typedefs at 792-807; stub-size cross-check `load_stub_sizes` 855 reads `pc_port/src/stubs/data_stubs.c`; per-map driver `extract_map` at 961. **Reuse**: its sym-file parser + VIN BIN reader + address->file-offset logic are the template for any editor tool that reads original map overlays. (Memory rule: never bulk-regen its outputs — hand-append.)
- **`tim_convert.py`** (440 lines) — TIM<->PNG batch converter with `extract`/`pack`/`info` subcommands; preserves pmode, VRAM target rect and CLUT rect via `.TIM.json` sidecars. `bgr555_to_rgba` line 96, `rgba_to_bgr555` 114, `real_width` (pmode-aware) 124, full `class Tim` parser at 153, `encode_png_to_tim_16bpp` 262. Needs Pillow. **Top lift for editor texture import/export.**
- **`gen_pal_filetable.py`** (119 lines) — decodes the 2310/2074-entry `g_FileTable` straight out of the PSX EXE; documents the 12-byte `s_FileInfo` bit layout in its docstring (word0 startSector:19|blockCount:12; word1 pathIdx:4|name0123:24; word2 name4567:24|type:4; 6-bit chars). Validated byte-exact vs USA. **The file-table codec for any tool that reads/writes SILENT./HILL.**
- `extract_anim_infos.py` (149) — extract a named ANIM_INFOS table from map BINs into C.
- `dump_disc_sym.py` (94) — dump original PSX bytes behind any symbol from a map overlay BIN (ground truth checker).
- `gen_map7_s03_boss_motion.py` (154) — final-boss motion-script block with PSX->PC pointer relocation.
- `audit_zero_stubs.py` (163) / `audit_stub_layout.py` (155) / `find_latent_stubs.py` (82) / `audit_map_sound_data.py` (169) / `check_map0_s01_pose_types.py` (52) — stub/data audits; not editor-relevant except as sym-map parsing examples.
- XA/FMV: `decode_xa_test.py` (161, reference XA-ADPCM decoder), `audit_xa_items.py`, `rename_fmv.py`, `find_str_sectors.py`, `find_str_magic.py`, `check_fmv_sector.py`, `check_xa_start.py`, `dump_sectors.py`, `dump_c1_*.py`, `submode_histogram.py` — audio/video, out of editor scope.

### silent-hill-decomp/tools/ (upstream decomp)

- **`silentassets/extract.py`** — parses `g_FileTable` from the EXE and extracts the SILENT./HILL. containers (this produced `disc_extract/`); knows all releases/flags, file-type names at top of file.
- **`silentassets/insertovl.py`** — re-inserts an overlay back into the disc image (VERSIONS table with per-release filetable offsets at lines 14-18). **This is the existing write-back path — critical for an editor that must ship edited data back onto a playable image, until a loose-file path is used instead.**
- **`maptool.py`** — besides ASM matching, parses map file headers: `--list MAP_NAME` lists character spawns from map headers, `--searchChara` finds maps containing a character ID (header comment lines 1-26). Contains working Python readers for map-overlay header structures.
- **`kaitai_scripts/`** — `ipd.ksy` (608 lines: full IPD spec — header, lm_header, model_infos, model_buffers, model_order_list, `ipd_collision_data`), `ilm.ksy` (210), `anm.ksy` (109). **ipd.ksy is the single best machine-readable IPD document in-house.** No plm.ksy/tim.ksy here (TIM spec is in museum's ksy dir).
- `bin2c.py`, `extract_enemy_rodata.py`, `extract_stalker_rodata.py` — rodata->C extraction patterns.
- Note: `pc_port/tools/` has no `extract.py`-style disc extractor of its own; `disc_extract/` at repo-sibling level (with `filetable.c.inc`, `fileenum.h.inc` at its root) is the pre-extracted corpus. `disc_extract/README.md` and `USAGE.md` are actually vgmstream's docs (leftover from audio work) — not SH format docs.

## 4. Format documentation found

- **`silent-hill-decomp/docs/File Formats.md`** — master table: every extension, purpose, and pointer to parser/doc. Key rows: IPD/PLM = local/global static models, both covered by Sparagas `sh1_model.bt` (external, github.com/Sparagas/Silent-Hill) and belek666 `sh_ipd2obj` (external IPD->OBJ converter); DMS -> in-repo `docs/file_formats/sh1_dms.bt`; TIM/TMD/VAB -> PsyQ SDK `filefrmt.pdf`. Also documents the SILENT./HILL. container scheme and folder purposes (BG/ = level TIM+IPD, ITEM/ = TIM+TMD+PLM).
- **`silent-hill-decomp/docs/file_formats/sh1_dms.bt`** — 010 Editor template for DMS cutscene files (by emoose): VECTOR3/SVECTOR3, DMSInterval, CameraFrame, CharacterFrame, DMSEntry structures.
- **`silent-hill-decomp/include/bodyprog/formats/`** — canonical C structs, directly compilable into C++ converter code: `ipd.h` (170 lines; `s_IpdHeader` at 149-168; collision structs with exact bitfields — `s_IpdCollSurface` lines 28-47 incl. `e_GroundType` 5-bit field, `s_IpdCollSubcell` 50-64, subcell ranges 79+), `lm.h` (56 lines; `s_LmHeader` at 34-47, `s_Material` 11-32 — materials reference textures by 8-char filename), `model.h` (66, `s_ModelHeader`), `tmd.h` (13), `anm.h` (32), `texture.h` (15). Runtime parsing/consumption of IPD lives in `src/bodyprog/gfx/bodyprog_80040B74.c` (`Ipd_HeaderCollisionDataGet` line 2155, `Ipd_ChunkDraw` line 2389) — the reference for how offsets are resolved to pointers at load.
- **`silent-hill-decomp/pc_port/docs/`** — semantics docs highly relevant to an editor: `trigger_zones.md` (raised-floor AABB zones, data structure at `include/bodyprog/bodyprog.h:1278`, -Y = up convention), `collision_technical_analysis.md`, `inventory_rendering_and_world_items.md`, `ordering_table_and_drawtag_pipeline.md`, `struct_offset_portability.md`.
- **`C:/Claude/silenthill/research/`** — `decomp_function_names.md` (function-naming proposals, not format docs) + a second decomp checkout; nothing format-new.
- **`C:/Claude/silenthill/cursor/`** — only `config.cfg`, `launcher/`, `release-nightly.ps1`; no format docs.

## 5. Toolchain availability

- **Python**: `python --version` -> **3.14.3** (`C:\Python314\python.exe`); `py` launcher works (3.14.3); a 3.13.14 also present. **Pillow 12.2.0 installed** (`import PIL` succeeds) — tim_convert.py runs as-is.
- **MSVC**: Visual Studio **2022 Community** installed; `vswhere.exe` present; `cl.exe` at `C:\Program Files\Microsoft Visual Studio\2022\Community\VC\Tools\MSVC\14.44.35207\bin\Hostx64\x64\cl.exe`.
- **CMake 4.3.1** and **Ninja 1.13.2** on PATH; MSYS2 MinGW64 **GCC/G++ 13.1.0** at `C:\msys64\mingw64\bin`.
- **vcpkg**: `C:\vcpkg\vcpkg.exe` exists (bootstrapped; no `installed/` dir yet). TrenchBroom vendors its own `trenchbroom/vcpkg/` and manages all deps except Qt via manifest `trenchbroom/vcpkg.json` (assimp, catch2, cpptrace, ctre, fmt, freeimage, freetype, miniz, stduuid, tinyxml2).
- **Qt: NOT installed.** No `C:\Qt`, no `qmake`/`qmake6` on PATH, no Qt cmake packages in msys2 mingw64, none under Program Files or user dir. `trenchbroom/BUILD.md:29` requires **Qt 6.10** (earlier versions "definitely not work"); Windows configure per `BUILD.md:76`: `cmake .. -G"Visual Studio 17 2022" -T v143 -A x64 -DCMAKE_PREFIX_PATH="<QT_INSTALL_DIR>\msvc2022_64"`. **This is the only missing piece for building TrenchBroom.**
- **TrenchBroom already checked out**: `C:/Claude/silenthill/trenchbroom`, origin = fork `SlickAmogus/TrenchBroom.git`, upstream = `TrenchBroom/TrenchBroom.git`, branch **`sh1-editor`**, HEAD `1b1099ab5` (upstream merge; no local-only commits yet, no build/ dir).

## 6. Reuse map — lift vs rewrite

**Lift as-is (converter layer, Python)**
- `pc_port/tools/tim_convert.py` `class Tim` + bgr555 codecs -> editor texture import/export (TIM->PNG for TrenchBroom material previews).
- `modelviewer/formats/tmd.py` -> TMD->OBJ/glTF for item/prop meshes.
- `tools/silentassets/extract.py` + `insertovl.py` -> container unpack/repack round-trip.
- `gen_pal_filetable.py` file-table bit codec -> file table read/write.
- `modelviewer/formats/anm.py` + museum `sh1.ts`/ksy -> animation/skeleton if the editor ever previews characters.

**Lift as spec, implement in C++ (editor core)**
- `include/bodyprog/formats/ipd.h`, `lm.h`, `model.h` — compile these headers (or transcribe verbatim) into the TrenchBroom-side IPD loader; they are exact and asserted (`STATIC_ASSERT_SIZEOF`).
- `tools/kaitai_scripts/ipd.ksy` — cross-check + can code-gen a parser (kaitai targets C++/Python/JS).
- `src/bodyprog/gfx/bodyprog_80040B74.c:2155,2389` — reference semantics for offset->pointer fixup and draw traversal.
- `docs/file_formats/sh1_dms.bt` + `pc_port/docs/trigger_zones.md` — cutscene and trigger-zone entity semantics.

**Reference only, do not lift**
- SHModelViewer `main.c` + `libgs_stub.c` — rendering-fidelity oracle and `--shot` regression harness; PSX-ABI-shaped code, wrong shape for a Qt editor's renderer.
- silent-hill-museum web app — visual identification workbench.

**Must write new (no in-house code exists)**
- IPD geometry -> editor-mesh converter (only external `sh_ipd2obj` referenced in docs; nothing in-house parses IPD *geometry* today — in-house IPD parsing is spec-level only).
- PLM parser (structurally = LM per `lm.h`, but no dedicated in-house tool).
- Any writer for IPD/PLM (nothing in-house writes model formats; only insertovl.py writes containers and tim_convert.py writes TIMs).

## Key files

- C:/Claude/silenthill/SHModelViewer/src/main.c — Entire viewer (389 lines): TMD header/object-table walk at 97-117, prim packet-size table + flag fixups at 130-170, GS scene setup 174-207, headless --shot 246-249/378-382
- C:/Claude/silenthill/silent-hill-decomp/pc_port/src/stubs/libgs_stub.c — The port's TMD/GS renderer SHModelViewer links (1589 lines): GsTMDfast* protos 104-119, GsFCALL4 dispatch 139-163, GsGetTMDObject 329, SH_TakeScreenshot 21
- C:/Claude/silenthill/modelviewer/formats/tmd.py — Clean standalone Python TMD parser (parse at 73, load at 145) — direct lift for converters
- C:/Claude/silenthill/modelviewer/formats/anm.py — ANM parser (parse 70, get_bone_world_transform 119)
- C:/Claude/silenthill/silent-hill-decomp/pc_port/tools/tim_convert.py — TIM<->PNG codec with VRAM/CLUT sidecars: class Tim at 153, bgr555 codecs 96/114, 16bpp encoder 262 — top lift for texture pipeline
- C:/Claude/silenthill/silent-hill-decomp/pc_port/tools/extract_map_data.py — Reads configs/USA/maps/sym.map*.txt + disc_extract/VIN/MAP*.BIN, emits pc_port/build_gen/extracted_data/{map}_data.c; sym parser 613, emitters 663-855, driver 961
- C:/Claude/silenthill/silent-hill-decomp/tools/kaitai_scripts/ipd.ksy — 608-line full IPD Kaitai spec (header, LM, model buffers, collision) — best in-house IPD document
- C:/Claude/silenthill/silent-hill-decomp/include/bodyprog/formats/ipd.h — Canonical IPD C structs with exact bitfields; s_IpdHeader 149-168, collision surfaces 28-64
- C:/Claude/silenthill/silent-hill-decomp/include/bodyprog/formats/lm.h — LM header + material structs (shared by PLM/ILM/IPD-embedded model data)
- C:/Claude/silenthill/silent-hill-decomp/tools/silentassets/extract.py — SILENT./HILL. container extractor (produced disc_extract/)
- C:/Claude/silenthill/silent-hill-decomp/tools/silentassets/insertovl.py — Overlay re-insertion into disc image — existing write-back path
- C:/Claude/silenthill/silent-hill-decomp/docs/File Formats.md — Master format table + container/folder documentation, external parser references (Sparagas sh1_model.bt, sh_ipd2obj)
- C:/Claude/silenthill/silent-hill-decomp/docs/file_formats/sh1_dms.bt — 010 Editor template for DMS cutscene files
- C:/Claude/silenthill/silent-hill-decomp/pc_port/docs/trigger_zones.md — Trigger-zone (raised floor AABB) data structure and semantics — editor-relevant entity type
- C:/Claude/silenthill/trenchbroom/BUILD.md — TrenchBroom build requirements: Qt 6.10 (line 29, NOT installed on machine), VS2022 configure line 76; repo already on branch sh1-editor
- C:/Claude/silenthill/silent-hill-decomp/src/bodyprog/gfx/bodyprog_80040B74.c — Runtime IPD consumption reference: Ipd_HeaderCollisionDataGet at 2155, Ipd_ChunkDraw at 2389

## Open questions

- Qt 6.10 is not installed anywhere on the machine — the only blocker for building TrenchBroom; needs the official installer (account required) or aqtinstall, targeting msvc2022_64.
- No in-house tool currently converts IPD geometry to a mesh (only spec-level parsing exists: ipd.ksy + ipd.h); confirm whether to port belek666's external sh_ipd2obj approach or write fresh from ipd.h + Ipd_ChunkDraw semantics.
- s_IpdHeader.unk_1D[51] (ipd.h:164) and several collision bitfields are still marked TODO/unknown in the decomp — writer support for IPD may require reversing these before round-trip editing is safe.
- PLM has no dedicated in-house parser or ksy; assumed structurally LM (lm.h) but unverified against actual ITEM/*.PLM files.
- disc_extract/README.md and USAGE.md are vgmstream leftovers, not extraction docs — the authoritative extraction procedure is tools/silentassets/extract.py; confirm which release flags were used to produce the current disc_extract tree.
