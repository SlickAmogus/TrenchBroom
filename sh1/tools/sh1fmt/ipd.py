"""IPD terrain-chunk parser (magic 0x14).

One IPD = one 40x40-unit map cell: header + collision block (kept opaque here,
offsets relative to file+0x54) + embedded LM geometry archive. Layout authority:
pc_port/src/ipd_reformat.c. Coordinates are Q23.8 (256 = 1 world unit), +Y down;
model-instance rotations are Q12; instance t[0]/t[2] are cell-relative, t[1] is
absolute; cell world corner = (cellX*10240, 0, cellZ*10240) in Q8.
"""

import struct
from dataclasses import dataclass

from .lm import Lm

IPD_MAGIC = 0x14
CELL_Q8 = 10240  # 40.0 world units


def decode_name(raw):
    return raw.rstrip(b"\x00 ").decode("ascii")


@dataclass
class IpdModelInfo:
    is_global_plm: int
    name: str
    name_raw: bytes = b""


@dataclass
class IpdModelInstance:
    model_info_idx: int
    rot: list            # 3x3 rows of s16, Q12
    trans: tuple         # (x,y,z) s32 Q8; x/z cell-relative, y absolute
    file_off: int
    pad: int = 0         # s16 at +0x16


@dataclass
class IpdCollision:
    """Collision block: fixed header fields + subarrays kept as opaque bytes.
    All stored offsets are relative to file offset 0x54; the writer recomputes
    them. all_empty files (no collision) store 0 for every offset."""
    position_x: int
    position_z: int
    subcell_size: int
    count_x: int
    count_z: int
    split_verts: bytes   # SVECTOR3[n], 6 B each
    surfaces: bytes      # 12 B each
    subcells: bytes      # 10 B each
    ptr18: bytes         # 10 B each
    ranges: bytes        # 4 B x (count_x*count_z + 1)
    ptr28: bytes         # u8[]
    ptr2c: bytes         # u8[]

    @property
    def all_empty(self):
        return not (self.split_verts or self.surfaces or self.subcells
                    or self.ptr18 or self.ranges or self.ptr28 or self.ptr2c)


@dataclass
class IpdModelBuffer:
    instance_count: int
    billboard_count: int
    subcell_count: int
    bounds: tuple        # (minX, maxX, minZ, maxZ) s16 Q8 cell-relative
    instances: list      # [IpdModelInstance]
    billboards: list     # [(x, y, z, type)] s16
    rects: list          # [(minX, maxX, minZ, maxZ)] s16 visibility rects


@dataclass
class Ipd:
    cell_x: int
    cell_z: int
    model_infos: list    # [IpdModelInfo]
    model_buffers: list  # [IpdModelBuffer]
    model_order: bytes   # indices into model_buffers
    draw_table: bytes    # 5x5x2 {start,count} pairs into model_order
    lm: Lm
    collision_raw: bytes # 0x54..0x188 header block (subarrays referenced within file)
    raw: bytes           # entire original file (for in-place patch round-trips)
    is_loaded: int = 0   # byte 0x01 — undefined on disc, preserved verbatim
    collision: IpdCollision = None

    @classmethod
    def parse(cls, data):
        if data[0] != IPD_MAGIC:
            raise ValueError(f"bad IPD magic {data[0]:#x}")
        is_loaded = data[1]
        cell_x, cell_z = struct.unpack_from("<bb", data, 2)
        lm_off, model_count, buffer_count, order_count = struct.unpack_from(
            "<IBBB", data, 4)
        model_info_off, model_buffers_off = struct.unpack_from("<II", data, 0x14)
        draw_table = data[0x1C : 0x1C + 50]
        model_order_off = struct.unpack_from("<I", data, 0x50)[0]

        infos = []
        for i in range(model_count):
            off = model_info_off + i * 16
            infos.append(IpdModelInfo(data[off], decode_name(data[off + 4 : off + 12]),
                                      bytes(data[off + 4 : off + 12])))

        buffers = []
        for i in range(buffer_count):
            off = model_buffers_off + i * 24
            inst_n, bb_n, rect_n = struct.unpack_from("<BBB", data, off)
            bounds = struct.unpack_from("<hhhh", data, off + 4)
            inst_off, bb_off, rect_off = struct.unpack_from("<III", data, off + 0xC)

            instances = []
            for j in range(inst_n):
                p = inst_off + j * 36
                idx = struct.unpack_from("<I", data, p)[0]
                m = struct.unpack_from("<9h", data, p + 4)
                rot = [m[0:3], m[3:6], m[6:9]]
                pad = struct.unpack_from("<h", data, p + 0x16)[0]
                trans = struct.unpack_from("<3i", data, p + 0x18)
                instances.append(IpdModelInstance(idx, rot, trans, p, pad))

            billboards = [struct.unpack_from("<4h", data, bb_off + j * 8)
                          for j in range(bb_n)]
            rects = [struct.unpack_from("<4h", data, rect_off + j * 8)
                     for j in range(rect_n)]
            buffers.append(IpdModelBuffer(inst_n, bb_n, rect_n, bounds,
                                          instances, billboards, rects))

        model_order = data[model_order_off : model_order_off + order_count]
        lm = Lm.parse(data, lm_off)
        collision = cls._parse_collision(data)
        return cls(cell_x, cell_z, infos, buffers, model_order, draw_table,
                   lm, data[0x54:0x188], data, is_loaded, collision)

    @staticmethod
    def _parse_collision(data):
        C = 0x54
        px, pz, bits = struct.unpack_from("<iiI", data, C)
        svn, sfn, scn, p18n = (bits & 0xFF, (bits >> 8) & 0xFF,
                               (bits >> 16) & 0xFF, (bits >> 24) & 0xFF)
        o_sv, o_sf, o_sc, o_18 = struct.unpack_from("<IIII", data, C + 0xC)
        size, cx, cz = struct.unpack_from("<hBB", data, C + 0x1C)
        o_rng = struct.unpack_from("<I", data, C + 0x20)[0]
        f24, f26 = struct.unpack_from("<HH", data, C + 0x24)
        o_28, o_2c = struct.unpack_from("<II", data, C + 0x28)

        def arr(off, n):
            return bytes(data[C + off : C + off + n]) if n else b""

        return IpdCollision(
            px, pz, size, cx, cz,
            arr(o_sv, 6 * svn), arr(o_sf, 12 * sfn), arr(o_sc, 10 * scn),
            arr(o_18, 10 * p18n),
            arr(o_rng, 4 * (cx * cz + 1)) if cx * cz else b"",
            arr(o_28, f24), arr(o_2c, f26))
