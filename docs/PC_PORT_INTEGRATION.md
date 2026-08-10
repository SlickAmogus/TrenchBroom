# PC Port Integration Spec — Level Editor Support

Engine-level changes the silent-hill-decomp PC port needs so the editor can go
beyond size-invariant edits. **Do not apply while the VRAM/texture-residency
rework session is in flight** — every change below touches the same files that
rework owns (`fsqueue_3.c`, texture upload, PsyCross). Apply on top of its
result, re-reading the landed code first; line numbers below are pre-rework.

Guiding principle (user requirement): the game stays functionally 1:1 and all
original code paths remain intact; every change is an `#ifdef SH_PC_PORT`
addition, preferably in pc_port/ or PsyCross, never a behavior change when the
feature is off.

## 0. Precondition: validate the loose-file loader - DONE

`allow_loose_files` is **confirmed working in game** (user-verified: a compiled
IPD edit and replaced textures both showed up in the otherworld sewer). The
staged smoke test remains useful for re-checking after port changes: `sh1/tools/loose_smoke_test.py` stages 1-3 (unmodified IPD copy → red
TIM → real 13-byte IPD edit), each verified in the otherworld sewer
(map6_s03). Stage 1 rendering normally proves the read path; log line visible
with `SH_LOOSE_VERBOSE=1`. Known caveat to verify: the probe path is
CWD-relative (`"gamedata/load/%s/%s"`, fsqueue_3.c:281) — launching the exe
from another directory silently misses; consider switching to
`PcPort_GetGameDataPath()`.

## 0b. What changed in the port since this spec was written

Re-read before implementing anything below; line numbers here predate it.

- **IPD header validation** (decomp `f9caf3432`): `IpdHeader_FixOffsets_PC` now
  bounds-checks every section offset and requires the LM magic+version at
  `lmHdrOff` as a tail-arrival sentinel. A loose IPD that fails is skipped and
  retried every frame - i.e. a bad compile looks like "nothing happened", with
  `[IPD-VAL]` lines in the log. The converter twin of this check is
  `sh1/tools/validate_port_compat.py`; run it on compiler output.
- **Oversized loose models exist now for CHARA**: `pc_port/src/pc_big_lm.c`
  (ILM) and `pc_big_tmd.c` (item TMD) register PC-owned buffers whose capacity
  lifts the loose-file size gate via `Pc_BigLm_DestCapacity` in
  `Fs_QueueTickRead`. **This is the working in-tree template for item 1 below** -
  an IPD equivalent would follow the same shape (registry keyed by file index,
  calloc'd buffer, capacity hook) rather than needing new invention.
- **Shared LM validator**: `pc_port/include/lm_validate.h` validates raw
  ILM/PLM bytes and is explicitly written to be a converter twin. If `map2ipd
  --full` ever emits PLM data, validate against these rules.
- **Per-CLUT-row PNG/DDS texture overrides** are live
  (`gamedata/load/BG/<SHEET>.TIM.p<NN>.png`), which removes the palette and
  resolution limits for texture modding entirely. `sh1/tools/textures_to_game.py`
  targets this path; item 3's "custom textures" need is largely met for BG
  sheets already.

## 1. Remove the loose-file size cap

Today a loose file larger than the file table's `blockCount*256` (sector-
aligned) buffer is misrouted into the hi-res TIM path (fsqueue_3.c:289-357,
buffer size at :292 and :52). Fix:

- In `Fs_QueueTickRead`'s SH_PC_PORT block: stat the loose file first; if
  `size > bufSize` and the entry is NOT a TIM destined for the hi-res path,
  reallocate/grow `entry->data` to the loose size (the FS queue's arena
  allocator `Fs_QueueAllocEntryData` at fsqueue_3.c:52 and the overlap math at
  :100-103 must honor the grown size — audit both).
- IPD chunk slots: `Ipd_ActiveChunksClear` (bodyprog_80040B74.c:726-844)
  slices the 0x2C000 buffer into 45056 B (exterior) / 90112 B (interior)
  slots; PC extra-residency slots are already 90112 B callocs. Under
  SH_PC_PORT, size each slot to `max(slotSize, looseFileSize)` at load time —
  or simplest: calloc every slot at a PC constant (e.g. 512 KB) since PC has
  no RAM budget. The in-memory IPD is relocated in place, so a bigger buffer
  is sufficient; nothing else assumes the slot size except the eviction
  cost heuristic (Ipd_FreeChunkFind :1822-1902), which is size-agnostic.
- Global LM buffer (`GLOBAL_LM_BUFFER`) gets the same treatment for grown
  `*_GLB.PLM` files.
- Fix the latent bug first: oversized non-TIM loose files leak stale
  `HiresPending` entries keyed by recycled queue-entry pointers
  (fsqueue_3.c:161-212) — must be popped on ANY completion path.

## 2. New IPD cells without file-table rebuilds

`Map_MakeIpdGrid` (bodyprog_80040B74.c:846-895) builds the cell grid purely
from `g_FileTable` name scans, so a brand-new `TAGxxzz.IPD` cannot load even
as a loose file. Add to its SH_PC_PORT block: after the table scan, enumerate
`gamedata/load/BG/<TAG>????.IPD`, parse cell coords with the existing
`ConvertHexToS8`, and place entries the table didn't provide. These need a
synthetic file index — reserve a PC-only range above FS_FILE_COUNT with a
side table of {name, path, size}, and teach the FS queue to route those
indices straight to the loose path (they have no disc sectors).

## 3. Cross-map / global custom assets

Texture resolution is already name-based (`Material_TimFileNameGet` →
`Fs_FindNextFile`), so once (2)'s synthetic index mechanism exists, the same
side table lets a map reference ANY TIM name dropped into gamedata/load/BG/ —
including brand-new sheets shared across areas. Same for models: `map2ipd
--full` can emit materials naming new TIMs, and IPD modelInfo entries resolve
global models by name from the area PLM; a PC-side "extra PLM" (e.g.
`gamedata/load/BG/CUSTOM_GLB.PLM`, loaded after the area PLM and searched as
a fallback in `LmHeader_ModelHeaderSearch`, bodyprog_80040B74.c:2307-2351)
gives mods a shared model library without touching retail files.

## 4. VRAM interaction (coordinate with the residency rework)

Map texture slots are the fixed 8 full-page + 2 half-page VRAM pool
(Ipd_TexturesInit, bodyprog_80040B74.c:528-559). Custom maps that reference
more than 10 sheets per active chunk set will thrash the pool exactly like
the known mall BLACK-flicker class. The VRAM rework (removing the pool limit,
per-material PC textures — see project_vram_pool_removal_task) is the real
fix; the editor pipeline needs no change either way because it keys textures
by material name, not by runtime slot.

## 5. Size validation ownership

Until (1) lands, `map2ipd` enforces: output size == original (in-place patch
mode) or warns loudly when --full output exceeds the original sector-aligned
size / chunk slot caps. When (1) lands, relax the caps in
`sh1/tools/map2ipd.py` (single constant near the top) and delete the warning.
