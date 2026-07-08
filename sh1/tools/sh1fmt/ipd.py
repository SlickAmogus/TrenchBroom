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


@dataclass
class IpdModelInstance:
    model_info_idx: int
    rot: list            # 3x3 rows of s16, Q12
    trans: tuple         # (x,y,z) s32 Q8; x/z cell-relative, y absolute
    file_off: int


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

    @classmethod
    def parse(cls, data):
        if data[0] != IPD_MAGIC:
            raise ValueError(f"bad IPD magic {data[0]:#x}")
        cell_x, cell_z = struct.unpack_from("<bb", data, 2)
        lm_off, model_count, buffer_count, order_count = struct.unpack_from(
            "<IBBB", data, 4)
        model_info_off, model_buffers_off = struct.unpack_from("<II", data, 0x14)
        draw_table = data[0x1C : 0x1C + 50]
        model_order_off = struct.unpack_from("<I", data, 0x50)[0]

        infos = []
        for i in range(model_count):
            off = model_info_off + i * 16
            infos.append(IpdModelInfo(data[off], decode_name(data[off + 4 : off + 12])))

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
                trans = struct.unpack_from("<3i", data, p + 0x18)
                instances.append(IpdModelInstance(idx, rot, trans, p))

            billboards = [struct.unpack_from("<4h", data, bb_off + j * 8)
                          for j in range(bb_n)]
            rects = [struct.unpack_from("<4h", data, rect_off + j * 8)
                     for j in range(rect_n)]
            buffers.append(IpdModelBuffer(inst_n, bb_n, rect_n, bounds,
                                          instances, billboards, rects))

        model_order = data[model_order_off : model_order_off + order_count]
        lm = Lm.parse(data, lm_off)
        return cls(cell_x, cell_z, infos, buffers, model_order, draw_table,
                   lm, data[0x54:0x188], data)
