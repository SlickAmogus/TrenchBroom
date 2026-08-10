"""Pack an edited PNG back into a Silent Hill TIM for loose-file replacement.

The original TIM provides the header rects, pixel mode, and all CLUT rows; only
the target CLUT row's palette and the pixel indices are rewritten, so every
other palette variant of the sheet keeps working. Packing is identity-
preserving: pixels whose color still matches their original palette entry keep
their original index, so an unedited PNG repacks to a byte-identical TIM.

PSX color rules applied on encode: fully transparent PNG pixel -> texel value
0x0000; opaque pure black -> 0x8000 (STP-set black — renders black, not
transparent). If the edit uses more colors than the palette can hold (15/255 +
transparent), the image is quantized with a warning.

Usage:
  python png2tim.py --png edited.png --tim BG/DRU01F.TIM [--row 0]
                    [-o out.TIM]   # default: <loose dir>/<TIM name>
"""

import argparse
import struct
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from sh1fmt import Tim

DEFAULT_LOOSE = (r"C:\Claude\silenthill\silent-hill-decomp\pc_port\build"
                 r"\gamedata\load\BG")


def rgba_to_c16(px):
    r, g, b, a = px
    if a < 128:
        return 0x0000
    c = (r >> 3) | ((g >> 3) << 5) | ((b >> 3) << 10)
    return c if c != 0 else 0x8000  # opaque black must not encode as transparent


def c16_to_rgba(c16):
    if c16 == 0:
        return (0, 0, 0, 0)
    r = (c16 & 0x1F) << 3
    g = ((c16 >> 5) & 0x1F) << 3
    b = ((c16 >> 10) & 0x1F) << 3
    return (r | (r >> 5), g | (g >> 5), b | (b >> 5), 255)


def color_key(c16):
    """Visual identity of a palette entry / pixel color, ignoring the STP bit
    (PNG cannot carry it): 0x0000 is transparent; STP-set black is opaque
    black; anything else keys on its 15-bit RGB."""
    if c16 == 0:
        return "transparent"
    rgb = c16 & 0x7FFF
    return "black" if rgb == 0 else rgb


def build_palette(tim, row, keys_needed, warn):
    """16-bit entries for the target row, reusing original slots (with their
    original STP bits) wherever the color survives, so unedited pixels keep
    their exact indices and entries."""
    size = 16 if tim.pmode == 0 else 256
    original = [tim.clut_entry(row, i) for i in range(min(size, tim.clut_w))]
    original += [0] * (size - len(original))

    entries = list(original)
    assigned = {}                       # color key -> index
    for i, e in enumerate(original):
        assigned.setdefault(color_key(e), i)

    missing = [k for k in keys_needed if k not in assigned]
    used = set(keys_needed)
    # a slot is reusable if its color is unused, or it duplicates another slot
    # that is already the canonical entry for that color
    free = [i for i, e in enumerate(original)
            if color_key(e) not in used or assigned[color_key(e)] != i]
    if len(missing) > len(free):
        warn(f"palette overflow: {len(missing)} new colors, {len(free)} free "
             f"slots - image will be quantized")
        return None
    for k in missing:
        i = free.pop(0)
        entries[i] = 0 if k == "transparent" else 0x8000 if k == "black" else k
        assigned[k] = i
    return entries, assigned


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--png", required=True)
    ap.add_argument("--tim", required=True, help="original TIM (header/CLUT donor)")
    ap.add_argument("--row", type=int, default=0, help="CLUT row to rewrite")
    ap.add_argument("-o", "--out", default=None,
                    help=f"output path (default: {DEFAULT_LOOSE}\\<name>)")
    args = ap.parse_args()

    from PIL import Image
    tim_path = Path(args.tim)
    raw = tim_path.read_bytes()
    tim = Tim.parse(raw)
    if tim.pmode not in (0, 1, 2):
        sys.exit(f"unsupported pmode {tim.pmode}")

    img = Image.open(args.png).convert("RGBA")
    if img.size != (tim.width, tim.height):
        sys.exit(f"size mismatch: PNG {img.size}, TIM {(tim.width, tim.height)}")

    warnings = []
    px = list(img.getdata())
    colors = [rgba_to_c16(p) for p in px]

    if tim.pmode == 2:
        # 16bpp direct color: no palette work
        pixel_bytes = b"".join(struct.pack("<H", c) for c in colors)
        new_clut = tim.clut
    else:
        palette_cap = 16 if tim.pmode == 0 else 256
        keys = [color_key(c) for c in colors]
        distinct = list(dict.fromkeys(keys))
        result = build_palette(tim, args.row, distinct, warnings.append)
        if result is None:
            # quantize down to what fits, then rebuild
            keep = palette_cap - (1 if "transparent" in distinct else 0)
            quant = img.convert("RGB").quantize(colors=keep).convert("RGB")
            qdata = list(quant.getdata())
            colors = [0 if p[3] < 128 else rgba_to_c16((*q, 255))
                      for p, q in zip(px, qdata)]
            keys = [color_key(c) for c in colors]
            distinct = list(dict.fromkeys(keys))
            result = build_palette(tim, args.row, distinct, warnings.append)
            if result is None:
                sys.exit("quantization failed to fit the palette")
        entries, assigned = result

        # identity-preserving indices: keep the original nibble/byte when its
        # palette entry still shows the pixel's color
        orig_idx = []
        stored = tim.stored_w
        for y in range(tim.height):
            base = y * stored * 2
            for x in range(tim.width):
                if tim.pmode == 0:
                    b_ = tim.pixels[base + (x >> 1)]
                    orig_idx.append((b_ >> ((x & 1) * 4)) & 0xF)
                else:
                    orig_idx.append(tim.pixels[base + x])

        indices = []
        for k, oi in zip(keys, orig_idx):
            if oi < len(entries) and color_key(entries[oi]) == k:
                indices.append(oi)
            else:
                indices.append(assigned[k])

        if tim.pmode == 0:
            pixel_bytes = bytearray(tim.stored_w * tim.height * 2)
            for i, idx in enumerate(indices):
                y, x = divmod(i, tim.width)
                off = y * tim.stored_w * 2 + (x >> 1)
                if x & 1:
                    pixel_bytes[off] |= idx << 4
                else:
                    pixel_bytes[off] |= idx
            pixel_bytes = bytes(pixel_bytes)
        else:
            pixel_bytes = bytes(indices)

        clut = bytearray(tim.clut)
        for i, e in enumerate(entries):
            struct.pack_into("<H", clut, (args.row * tim.clut_w + i) * 2, e)
        new_clut = bytes(clut)

    # Patch the original file in place (block sizes/padding preserved exactly):
    # walk the header to find where CLUT entries and pixel data live on disk.
    out = bytearray(raw)
    off = 8
    if tim.clut:
        clut_block_size = struct.unpack_from("<I", raw, off)[0]
        out[off + 12 : off + 12 + len(new_clut)] = new_clut
        off += clut_block_size
    out[off + 12 : off + 12 + len(pixel_bytes)] = pixel_bytes

    from sh1fmt import paths
    out_path = Path(args.out) if args.out else paths.loose_bg_dir() / tim_path.name
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_bytes(bytes(out))

    for w in warnings:
        print(f"WARN: {w}")
    same = bytes(out) == raw
    print(f"wrote {out_path} ({len(out)} bytes, original {len(raw)}"
          f"{', byte-identical' if same else ''})")
    if len(out) != len(raw):
        print("WARN: size differs from original - loose loader requires <= "
              "original sector-aligned size")


if __name__ == "__main__":
    main()
