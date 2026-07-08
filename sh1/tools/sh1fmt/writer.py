"""IPD serializer — the inverse of Ipd.parse.

Reproduces the retail layout byte-for-byte (validated by validate_writer.py over
all 493 BG IPDs). Canonical section order and packing rules, established by a
corpus-wide survey:

  header(0x54) | collision fixed block(0x134) | modelInfo[16n] | modelBuffers[24n]
  | per buffer: instances[36n], billboards[8n], rects[8n] | modelOrderList[u8 n]
  | align4 splitVerts | align4 surfaces | align4 subcells | align4 ptr18
  | align4 ranges | ptr28 | ptr2C
  | align4 LM header(20) | materials[24n] | modelHdrs[16n]
  | modelCount zero bytes (unknown per-model array, always 0 on disc)
  | align4 modelOrder[u8 n]
  | per model: align4 meshHdrs[24n]
  |   per mesh: align4 prims[20n] | vertsXy[4n] | vertsZ[2n] | align4 normals[4n]
  |             slots[u8 n]

- All alignment padding is zero bytes.
- Collision subarray offsets are stored relative to 0x54; every other offset is
  file-relative except LM-internal offsets (relative to the LM header).
- Empty arrays store the cursor position they would occupy (after their own
  alignment); files with NO collision at all store 0 for all seven offsets.
- modelInfo placeholder u32, all pads, the collision scratch block and the LM
  "hidden" per-model array are all zero in every retail file (surveyed).
- Retail files carry garbage after the last section up to a 256-byte boundary;
  write_ipd emits the body only — callers append the original tail (identity)
  or zero-pad to 256 (write_ipd_file).
"""

import struct

COLL_BASE = 0x54
HDR_END = 0x188


def _align4(buf):
    while len(buf) % 4:
        buf.append(0)


class _Layout:
    """First pass: compute every section offset with the canonical rules."""

    def __init__(self, ipd):
        self.ipd = ipd
        cur = HDR_END
        self.model_info_off = cur
        cur += 16 * len(ipd.model_infos)
        self.model_buffers_off = cur
        cur += 24 * len(ipd.model_buffers)
        self.buf_offs = []
        for b in ipd.model_buffers:
            io = cur
            cur += 36 * len(b.instances)
            bo = cur
            cur += 8 * len(b.billboards)
            ro = cur
            cur += 8 * len(b.rects)
            self.buf_offs.append((io, bo, ro))
        self.model_order_off = cur
        cur += len(ipd.model_order)

        c = ipd.collision
        if c.all_empty:
            self.coll_offs = dict.fromkeys(
                ("sv", "sf", "sc", "p18", "rng", "p28", "p2c"), 0)
        else:
            offs = {}
            for key, blob, align in (("sv", c.split_verts, 4),
                                     ("sf", c.surfaces, 4),
                                     ("sc", c.subcells, 4),
                                     ("p18", c.ptr18, 4),
                                     ("rng", c.ranges, 4),
                                     ("p28", c.ptr28, 1),
                                     ("p2c", c.ptr2c, 1)):
                if align == 4:
                    cur = (cur + 3) & ~3
                offs[key] = cur - COLL_BASE
                cur += len(blob)
            self.coll_offs = offs

        cur = (cur + 3) & ~3
        self.lm_off = cur
        L = cur
        cur += 20
        self.lm_materials_off = cur - L
        cur += 24 * len(ipd.lm.materials)
        self.lm_model_hdrs_off = cur - L
        cur += 16 * len(ipd.lm.models)
        cur += len(ipd.lm.models)          # hidden zero array
        cur = (cur + 3) & ~3
        self.lm_model_order_off = cur - L
        cur += len(ipd.lm.model_order)
        self.mesh_hdr_offs = []            # per model: rel L
        self.mesh_data_offs = []           # per model: [per mesh (p,xy,z,n,s)] rel L
        for m in ipd.lm.models:
            cur = (cur + 3) & ~3
            self.mesh_hdr_offs.append(cur - L)
            cur += 24 * len(m.meshes)
            per_mesh = []
            for mesh in m.meshes:
                cur = (cur + 3) & ~3
                po = cur - L
                cur += 20 * len(mesh.prims)
                xo = cur - L
                cur += 4 * len(mesh.verts)
                zo = cur - L
                cur += 2 * len(mesh.verts)
                cur = (cur + 3) & ~3
                no = cur - L
                cur += 4 * len(mesh.normals)
                so = cur - L
                cur += len(mesh.lighting_slots)
                per_mesh.append((po, xo, zo, no, so))
            self.mesh_data_offs.append(per_mesh)
        self.end = cur


def write_ipd(ipd):
    """Serialize a (possibly mutated) Ipd back to body bytes (no tail padding)."""
    lay = _Layout(ipd)
    out = bytearray()

    # --- header 0x00-0x53
    out += struct.pack("<BBbb", 0x14, ipd.is_loaded, ipd.cell_x, ipd.cell_z)
    out += struct.pack("<IBBB", lay.lm_off, len(ipd.model_infos),
                       len(ipd.model_buffers), len(ipd.model_order))
    out += bytes(9)
    out += struct.pack("<II", lay.model_info_off, lay.model_buffers_off)
    assert len(ipd.draw_table) == 50
    out += ipd.draw_table
    out += bytes(2)
    out += struct.pack("<I", lay.model_order_off)
    assert len(out) == COLL_BASE

    # --- collision fixed block
    c = ipd.collision
    svn = len(c.split_verts) // 6
    sfn = len(c.surfaces) // 12
    scn = len(c.subcells) // 10
    p18n = len(c.ptr18) // 10
    out += struct.pack("<iiI", c.position_x, c.position_z,
                       svn | (sfn << 8) | (scn << 16) | (p18n << 24))
    o = lay.coll_offs
    out += struct.pack("<IIII", o["sv"], o["sf"], o["sc"], o["p18"])
    out += struct.pack("<hBB", c.subcell_size, c.count_x, c.count_z)
    out += struct.pack("<IHH", o["rng"], len(c.ptr28), len(c.ptr2c))
    out += struct.pack("<II", o["p28"], o["p2c"])
    out += bytes(0x134 - 0x30)             # checkCount + pad + scratch, all zero
    assert len(out) == HDR_END

    # --- model infos
    for info in ipd.model_infos:
        name = info.name_raw or info.name.encode("ascii").ljust(8, b"\x00")
        out += struct.pack("<B3x", info.is_global_plm) + name + bytes(4)

    # --- model buffers + subarrays
    for b, (io, bo, ro) in zip(ipd.model_buffers, lay.buf_offs):
        out += struct.pack("<BBBB4h", len(b.instances), len(b.billboards),
                           len(b.rects), 0, *b.bounds)
        out += struct.pack("<III", io, bo, ro)
    for b in ipd.model_buffers:
        for inst in b.instances:
            out += struct.pack("<I", inst.model_info_idx)
            out += struct.pack("<9h", *inst.rot[0], *inst.rot[1], *inst.rot[2])
            out += struct.pack("<h", inst.pad)
            out += struct.pack("<3i", *inst.trans)
        for bb in b.billboards:
            out += struct.pack("<4h", *bb)
        for r in b.rects:
            out += struct.pack("<4h", *r)

    # --- model order list
    out += ipd.model_order

    # --- collision subarrays
    if not c.all_empty:
        for blob, align in ((c.split_verts, 4), (c.surfaces, 4), (c.subcells, 4),
                            (c.ptr18, 4), (c.ranges, 4), (c.ptr28, 1),
                            (c.ptr2c, 1)):
            if align == 4:
                _align4(out)
            out += blob

    # --- LM
    _align4(out)
    assert len(out) == lay.lm_off
    lm = ipd.lm
    out += struct.pack("<BBBB", 0x30, 6, lm.is_loaded, len(lm.materials))
    out += struct.pack("<IB3xII", lay.lm_materials_off, len(lm.models),
                       lay.lm_model_hdrs_off, lay.lm_model_order_off)
    for mat in lm.materials:
        name = mat.name_raw or mat.name.encode("ascii").ljust(8, b"\x00")
        out += name + struct.pack("<IBB", 0, mat.field_c, mat.unk_d) + bytes(10)
    for m, mh_off in zip(lm.models, lay.mesh_hdr_offs):
        name = m.name_raw or m.name.encode("ascii").ljust(8, b"\x00")
        out += name + struct.pack("<BBBBI", len(m.meshes), m.vertex_offset,
                                  m.normal_offset, m.flags, mh_off)
    out += bytes(len(lm.models))           # hidden per-model array
    _align4(out)
    out += lm.model_order

    for m, mh_off, data_offs in zip(lm.models, lay.mesh_hdr_offs,
                                    lay.mesh_data_offs):
        _align4(out)
        assert len(out) == lay.lm_off + mh_off
        for mesh, (po, xo, zo, no, so) in zip(m.meshes, data_offs):
            out += struct.pack("<BBBBIIIII", len(mesh.prims), len(mesh.verts),
                               len(mesh.normals), len(mesh.lighting_slots),
                               po, xo, zo, no, so)
        for mesh, (po, xo, zo, no, so) in zip(m.meshes, data_offs):
            _align4(out)
            assert len(out) == lay.lm_off + po
            for p in mesh.prims:
                mat_bits = p.material_idx & 0x7F
                field6 = (p.tpage & 0xFF) | (mat_bits << 8) \
                    | ((p.is_transparent & 1) << 15)
                out += struct.pack("<BBHBBHBBBB",
                                   p.uv[0][0], p.uv[0][1], p.clut,
                                   p.uv[1][0], p.uv[1][1], field6,
                                   p.uv[2][0], p.uv[2][1],
                                   p.uv[3][0], p.uv[3][1])
                out += bytes(p.vi) + bytes(p.li)
            for v in mesh.verts:
                out += struct.pack("<hh", v[0], v[1])
            for v in mesh.verts:
                out += struct.pack("<h", v[2])
            _align4(out)
            for n in mesh.normals:
                out += struct.pack("<bbbB", *n)
            out += mesh.lighting_slots

    assert len(out) == lay.end
    return bytes(out)


def write_ipd_file(ipd, tail=None):
    """Full file bytes: body + tail (original garbage for identity, else zero
    padding to the 256-byte block size the file table requires)."""
    body = write_ipd(ipd)
    if tail is None:
        pad = (-len(body)) % 256
        return body + bytes(pad)
    return body + tail
