"""Reject IPDs the PC port would reject.

The port validates every IPD header before reformatting it in place
(IpdHeader_FixOffsets_PC, pc_port/src/ipd_reformat.c — added by decomp commit
f9caf3432 after a corruption hunt). A loose IPD that fails validation is
silently skipped and retried every frame, so the edit simply never appears.
This is the converter twin of that check: run it on anything map2ipd writes.

  python validate_port_compat.py <file-or-dir> [...]     # check outputs
  python validate_port_compat.py --retail                # prove the rules on
                                                         # all 493 disc IPDs
Exit code 1 if any file would be rejected.
"""

import struct
import sys
from pathlib import Path

from sh1fmt import paths
DISC = paths.bg_dir()
IPD_MAGIC = 0x14
LM_MAGIC = 0x30
LM_VERSION = 6
HDR_END = 0x188
MAX_IPD = 0x2C000          # largest chunk slot; the port's ceiling
MODEL_INFO_SIZE = 16
MODEL_BUFFER_SIZE = 24

# Chunk-slot caps: an IPD larger than its slot cannot be streamed at all.
SLOT_CAP_INTERIOR = 90112
SLOT_CAP_EXTERIOR = 45056
INTERIOR_TAGS = {"SC", "SU", "ER", "HP", "HU"}


def port_reject_reason(raw, name=""):
    """Mirror of the port's validation. Returns None if the port accepts."""
    if len(raw) < HDR_END:
        return f"file shorter than the 0x{HDR_END:X}-byte header"
    if raw[0] != IPD_MAGIC:
        return f"bad IPD magic {raw[0]:#x}"

    lm_off, model_count, buffer_count, order_count = struct.unpack_from("<IBBB", raw, 4)
    model_info_off, model_buffers_off = struct.unpack_from("<II", raw, 0x14)
    model_order_off = struct.unpack_from("<I", raw, 0x50)[0]

    if lm_off < HDR_END or lm_off > MAX_IPD - 2:
        return f"lmHdrOff {lm_off:#x} outside [0x188, 0x{MAX_IPD - 2:X}]"
    if lm_off + 1 >= len(raw):
        return f"lmHdrOff {lm_off:#x} past end of file"
    if raw[lm_off] != LM_MAGIC or raw[lm_off + 1] != LM_VERSION:
        return (f"LM tail sentinel: expected {LM_MAGIC:#x} v{LM_VERSION} at "
                f"{lm_off:#x}, found {raw[lm_off]:#x} v{raw[lm_off + 1]}")
    if model_count and (model_info_off < HDR_END or model_info_off > lm_off
                        or model_count * MODEL_INFO_SIZE > lm_off - model_info_off):
        return f"modelInfo bounds (off {model_info_off:#x}, count {model_count})"
    if buffer_count and (model_buffers_off < HDR_END or model_buffers_off > lm_off
                         or buffer_count * MODEL_BUFFER_SIZE > lm_off - model_buffers_off):
        return f"modelBuffers bounds (off {model_buffers_off:#x}, count {buffer_count})"
    if order_count and (model_order_off < HDR_END or model_order_off > lm_off
                        or order_count > lm_off - model_order_off):
        return f"modelOrder bounds (off {model_order_off:#x}, count {order_count})"
    return None


def size_warnings(raw, name):
    """Non-fatal-to-validation but fatal-in-practice size limits."""
    out = []
    stem = Path(name).stem
    tag = "".join(c for c in stem if not c.isdigit())[:3].rstrip("0123456789ABCDEF")
    interior = any(stem.startswith(t) for t in INTERIOR_TAGS)
    cap = SLOT_CAP_INTERIOR if interior else SLOT_CAP_EXTERIOR
    if len(raw) > cap:
        out.append(f"{len(raw)} B exceeds the "
                   f"{'interior' if interior else 'exterior'} chunk-slot cap {cap} B "
                   f"- the game cannot stream it")
    orig = DISC / Path(name).name
    if orig.exists():
        orig_size = orig.stat().st_size
        if len(raw) > orig_size:
            out.append(f"{len(raw)} B exceeds the original {orig_size} B - the "
                       f"loose-file loader will ignore it (size gate comes from "
                       f"the compiled-in file table)")
    return out


def check(paths):
    files = []
    for p in paths:
        p = Path(p)
        files.extend(sorted(p.glob("*.IPD")) if p.is_dir() else [p])
    if not files:
        print("no .IPD files found")
        return 0

    bad = warned = 0
    for f in files:
        raw = f.read_bytes()
        reason = port_reject_reason(raw, f.name)
        if reason:
            bad += 1
            print(f"REJECT {f.name}: {reason}")
            continue
        warns = size_warnings(raw, f.name)
        for w in warns:
            warned += 1
            print(f"WARN   {f.name}: {w}")
        if not warns:
            print(f"ok     {f.name} ({len(raw)} B)")
    print(f"\n{len(files)} checked, {bad} would be REJECTED by the port, "
          f"{warned} size warnings")
    return 1 if bad else 0


def main():
    args = sys.argv[1:]
    if not args:
        print(__doc__)
        return 0
    if args[0] == "--retail":
        bad = [f.name for f in sorted(DISC.glob("*.IPD"))
               if port_reject_reason(f.read_bytes(), f.name)]
        print(f"retail corpus: {493 - len(bad)}/493 accepted by the port's rules")
        for n in bad[:20]:
            print(" ", n)
        return 1 if bad else 0
    return check(args)


if __name__ == "__main__":
    sys.exit(main())
