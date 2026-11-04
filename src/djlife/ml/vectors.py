"""Serializacao de vetores para o SQLite (float32 little-endian).

Fica fora do numpy de proposito: gravar/ler embedding nao pode depender do extra `ml`.
"""

from __future__ import annotations

import math
import struct
from collections.abc import Sequence

FLOAT_BYTES = 4


def pack(vector: Sequence[float]) -> bytes:
    """Vetor -> BLOB (float32 LE)."""
    if not vector:
        raise ValueError("embedding vazio")
    return struct.pack(f"<{len(vector)}f", *vector)


def unpack(blob: bytes) -> tuple[float, ...]:
    """BLOB -> vetor (float32 LE)."""
    if not blob or len(blob) % FLOAT_BYTES:
        raise ValueError("blob de embedding invalido")
    return struct.unpack(f"<{len(blob) // FLOAT_BYTES}f", blob)


def l2_normalize(vector: Sequence[float]) -> tuple[float, ...]:
    """Normaliza para norma 1, de modo que similaridade de cosseno seja produto interno."""
    norm = math.sqrt(math.fsum(value * value for value in vector))
    if norm == 0.0:
        raise ValueError("vetor nulo nao pode ser normalizado")
    return tuple(value / norm for value in vector)


def cosine(left: Sequence[float], right: Sequence[float]) -> float:
    """Cosseno entre dois vetores normalizados."""
    if len(left) != len(right):
        raise ValueError(f"dimensoes incompativeis: {len(left)} != {len(right)}")
    return math.fsum(a * b for a, b in zip(left, right, strict=True))
