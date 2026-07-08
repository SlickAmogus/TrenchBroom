"""PSX TIM image parser + per-CLUT-row RGBA export.

Map TIMs are 4bpp with a 16xN CLUT (one row per palette variant); a map prim's
`clut` field selects the row (row = clut // 64). Raw texel value 0x0000 is fully
transparent (PSX rule); the STP bit (bit 15) marks semi-transparent texels, which
map terrain renders additively — kept opaque here, flagged for the caller.
"""

import struct
from dataclasses import dataclass, field


@dataclass
class Tim:
    pmode: int              # 0=4bpp 1=8bpp 2=16bpp 3=24bpp
    clut_x: int
    clut_y: int
    clut_w: int             # entries per row (16 for map TIMs)
    clut_h: int             # number of rows
    clut: bytes             # raw u16 entries, row-major (may be empty)
    pix_x: int
    pix_y: int
    stored_w: int           # halfwords per row
    height: int
    pixels: bytes           # raw pixel data

    @property
    def width(self):
        return self.stored_w * (4, 2, 1, 1)[self.pmode]

    @classmethod
    def parse(cls, data):
        magic, flags = struct.unpack_from("<II", data, 0)
        if magic != 0x10:
            raise ValueError(f"bad TIM magic 0x{magic:x}")
        pmode = flags & 7
        off = 8
        clut_x = clut_y = clut_w = clut_h = 0
        clut = b""
        if flags & 8:
            size, clut_x, clut_y, clut_w, clut_h = struct.unpack_from("<IHHHH", data, off)
            clut = data[off + 12 : off + 12 + clut_w * clut_h * 2]
            off += size
        size, pix_x, pix_y, stored_w, height = struct.unpack_from("<IHHHH", data, off)
        pixels = data[off + 12 : off + 12 + stored_w * height * 2]
        return cls(pmode, clut_x, clut_y, clut_w, clut_h, clut,
                   pix_x, pix_y, stored_w, height, pixels)

    def clut_entry(self, row, idx):
        return struct.unpack_from("<H", self.clut, (row * self.clut_w + idx) * 2)[0]

    def rgba_for_clut_row(self, row):
        """Full image as flat RGBA bytes using CLUT row `row` (4/8bpp) or raw (16bpp).

        Returns (rgba_bytes, has_stp) where has_stp reports whether any visible
        texel had the STP semi-transparency bit set.
        """
        w, h = self.width, self.height
        out = bytearray(w * h * 4)
        has_stp = False

        def emit(i, c16):
            nonlocal has_stp
            if c16 == 0:
                return  # already 0,0,0,0
            r = (c16 & 0x1F) << 3
            g = ((c16 >> 5) & 0x1F) << 3
            b = ((c16 >> 10) & 0x1F) << 3
            if c16 & 0x8000:
                has_stp = True
            out[i * 4 + 0] = r | (r >> 5)
            out[i * 4 + 1] = g | (g >> 5)
            out[i * 4 + 2] = b | (b >> 5)
            out[i * 4 + 3] = 255

        if self.pmode == 0:
            for y in range(h):
                base = y * self.stored_w * 2
                for x in range(w):
                    byte = self.pixels[base + (x >> 1)]
                    idx = (byte >> ((x & 1) * 4)) & 0xF  # low nibble = left pixel
                    emit(y * w + x, self.clut_entry(row, idx))
        elif self.pmode == 1:
            for y in range(h):
                base = y * self.stored_w * 2
                for x in range(w):
                    emit(y * w + x, self.clut_entry(row, self.pixels[base + x]))
        elif self.pmode == 2:
            for i in range(w * h):
                emit(i, struct.unpack_from("<H", self.pixels, i * 2)[0])
        else:
            raise ValueError("24bpp TIM not supported")
        return bytes(out), has_stp

    def save_png(self, path, row=0):
        from PIL import Image
        rgba, has_stp = self.rgba_for_clut_row(row)
        img = Image.frombytes("RGBA", (self.width, self.height), rgba)
        img.save(path)
        return has_stp
