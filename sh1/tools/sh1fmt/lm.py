"""LM model-archive parser (magic 0x30, version 6).

The LM format is both the standalone .PLM file (offset 0) and the geometry
archive embedded in an .IPD (at the IPD header's lmHdrOff). All offsets inside
are relative to the LM base. Layout authority: pc_port/src/lm_reformat.c.
"""

import struct
from dataclasses import dataclass

LM_MAGIC = 0x30
LM_VERSION = 6


def decode_name(raw):
    return raw.rstrip(b"\x00 ").decode("ascii")


@dataclass
class Material:
    name: str            # 8-char TIM basename (append .TIM)
    field_c: int         # 1 = texture externally applied
    unk_d: int
    # tpage/clut/uv bases (field_E..field_16) are 0 on disc; runtime-patched
    file_off: int        # absolute file offset of this 24-byte record


@dataclass
class Primitive:
    uv: tuple            # ((u0,v0),(u1,v1),(u2,v2),(u3,v3)) texel coords
    clut: int            # row*64 on disc
    tpage: int           # 0 on disc
    material_idx: int    # -1 = untextured
    is_transparent: int  # bit15 of field_6 (additive blend in-game)
    vi: tuple            # 4 vertex indices (0xFF or repeated => triangle)
    li: tuple            # 4 lighting-slot indices
    file_off: int


@dataclass
class MeshHeader:
    prim_count: int
    vertex_count: int
    normal_count: int
    lighting_slot_count: int
    prims: list          # [Primitive]
    verts: list          # [(x,y,z)] s16 Q8 model-local
    normals: list        # [(nx,ny,nz,count)] s8,s8,s8,u8
    lighting_slots: bytes
    prims_off: int       # absolute file offsets of the raw arrays (for patching)
    verts_xy_off: int
    verts_z_off: int


@dataclass
class ModelHeader:
    name: str
    mesh_count: int
    vertex_offset: int
    normal_offset: int
    flags: int
    meshes: list


@dataclass
class Lm:
    materials: list      # [Material]
    models: list         # [ModelHeader]
    model_order: bytes
    base: int            # absolute file offset of the LM header

    def model_by_name(self, name):
        for m in self.models:
            if m.name == name:
                return m
        return None

    @classmethod
    def parse(cls, data, base=0):
        magic, version, _isloaded, material_count = struct.unpack_from("<BBBB", data, base)
        if magic != LM_MAGIC or version != LM_VERSION:
            raise ValueError(f"bad LM header {magic:#x} v{version} at {base:#x}")
        materials_off, model_count, _p0, _p1, _p2, model_hdrs_off, model_order_off = \
            struct.unpack_from("<IBBBBII", data, base + 4)

        materials = []
        for i in range(material_count):
            off = base + materials_off + i * 24
            name = decode_name(data[off : off + 8])
            _texptr, field_c, unk_d = struct.unpack_from("<IBB", data, off + 8)
            materials.append(Material(name, field_c, unk_d, off))

        models = []
        for i in range(model_count):
            off = base + model_hdrs_off + i * 16
            name = decode_name(data[off : off + 8])
            mesh_count, vertex_offset, normal_offset, flags = struct.unpack_from(
                "<BBBB", data, off + 8)
            mesh_hdrs_off = struct.unpack_from("<I", data, off + 12)[0]
            meshes = [cls._parse_mesh(data, base, base + mesh_hdrs_off + j * 24)
                      for j in range(mesh_count)]
            models.append(ModelHeader(name, mesh_count, vertex_offset, normal_offset,
                                      flags, meshes))

        model_order = data[base + model_order_off : base + model_order_off + model_count]
        return cls(materials, models, model_order, base)

    @staticmethod
    def _parse_mesh(data, base, off):
        (prim_count, vertex_count, normal_count, slot_count,
         prims_off, xy_off, z_off, normals_off, slots_off) = struct.unpack_from(
            "<BBBBIIIII", data, off)

        prims = []
        for k in range(prim_count):
            p = base + prims_off + k * 20
            u0, v0, clut, u1, v1, field_6, u2, v2, u3, v3 = struct.unpack_from(
                "<BBHBBHBBBB", data, p)
            vi = struct.unpack_from("<4B", data, p + 0xC)
            li = struct.unpack_from("<4B", data, p + 0x10)
            mat_idx = (field_6 >> 8) & 0x7F
            if mat_idx >= 0x40:
                mat_idx -= 0x80
            prims.append(Primitive(
                ((u0, v0), (u1, v1), (u2, v2), (u3, v3)),
                clut, field_6 & 0xFF, mat_idx, (field_6 >> 15) & 1, vi, li, p))

        verts = []
        for k in range(vertex_count):
            x, y = struct.unpack_from("<hh", data, base + xy_off + k * 4)
            z = struct.unpack_from("<h", data, base + z_off + k * 2)[0]
            verts.append((x, y, z))

        normals = [struct.unpack_from("<bbbB", data, base + normals_off + k * 4)
                   for k in range(normal_count)]
        slots = data[base + slots_off : base + slots_off + slot_count]

        return MeshHeader(prim_count, vertex_count, normal_count, slot_count,
                          prims, verts, normals, slots,
                          base + prims_off, base + xy_off, base + z_off)
