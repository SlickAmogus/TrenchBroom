"""Parsers for Silent Hill 1 (PSX) on-disc formats used by the level editor pipeline.

Byte-layout authority: silent-hill-decomp pc_port/src/ipd_reformat.c, lm_reformat.c,
include/bodyprog/formats/{ipd,lm,model}.h. See docs/research/ipd-map-geometry.md.
All values little-endian; all offsets file-relative unless noted.
"""

from .tim import Tim
from .lm import Lm, Material, ModelHeader, MeshHeader, Primitive
from .ipd import Ipd

__all__ = [
    "Tim", "Lm", "Material", "ModelHeader", "MeshHeader", "Primitive", "Ipd",
]
