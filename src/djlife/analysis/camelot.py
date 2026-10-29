"""Conversao de tonalidade para as notacoes Camelot e Open Key."""

from __future__ import annotations

MAJOR = "major"
MINOR = "minor"
MODES: tuple[str, ...] = (MAJOR, MINOR)

PITCH_NAMES: tuple[str, ...] = ("C", "Db", "D", "Eb", "E", "F", "Gb", "G", "Ab", "A", "Bb", "B")

# Indice = classe de altura (0 = C); valor = numero da posicao no wheel Camelot.
CAMELOT_NUMBERS: dict[str, tuple[int, ...]] = {
    MAJOR: (8, 3, 10, 5, 12, 7, 2, 9, 4, 11, 6, 1),
    MINOR: (5, 12, 7, 2, 9, 4, 11, 6, 1, 8, 3, 10),
}

CAMELOT_SUFFIX: dict[str, str] = {MAJOR: "B", MINOR: "A"}
OPEN_KEY_SUFFIX: dict[str, str] = {MAJOR: "d", MINOR: "m"}

# Open Key 1 = C maior (Camelot 8B) / A menor (Camelot 8A).
_OPEN_KEY_SHIFT = 4


def _check(pitch_class: int, mode: str) -> None:
    if mode not in CAMELOT_NUMBERS:
        raise ValueError(f"modo invalido: {mode!r}. Use {MAJOR} ou {MINOR}.")
    if not 0 <= pitch_class <= 11:
        raise ValueError(f"classe de altura fora de 0..11: {pitch_class!r}")


def camelot_code(pitch_class: int, mode: str) -> str:
    """Ex.: (9, 'minor') -> '8A'."""
    _check(pitch_class, mode)
    return f"{CAMELOT_NUMBERS[mode][pitch_class]}{CAMELOT_SUFFIX[mode]}"


def open_key_code(pitch_class: int, mode: str) -> str:
    """Ex.: (0, 'major') -> '1d'."""
    _check(pitch_class, mode)
    number = (CAMELOT_NUMBERS[mode][pitch_class] + _OPEN_KEY_SHIFT) % 12 + 1
    return f"{number}{OPEN_KEY_SUFFIX[mode]}"


def notations(pitch_class: int, mode: str) -> tuple[str, str]:
    """Devolve (Camelot, Open Key) para uma (classe de altura, modo)."""
    _check(pitch_class, mode)
    camelot = CAMELOT_NUMBERS[mode][pitch_class]
    number = (camelot + _OPEN_KEY_SHIFT) % 12 + 1
    return f"{camelot}{CAMELOT_SUFFIX[mode]}", f"{number}{OPEN_KEY_SUFFIX[mode]}"


def describe(pitch_class: int, mode: str) -> str:
    """Nome legivel: 'A minor', 'C major'."""
    _check(pitch_class, mode)
    return f"{PITCH_NAMES[pitch_class]} {mode}"
