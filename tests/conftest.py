import wave
from pathlib import Path

import pytest


@pytest.fixture
def make_wav():
    def _make(path: Path, frames: int = 1000) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        with wave.open(str(path), "wb") as handle:
            handle.setnchannels(1)
            handle.setsampwidth(2)
            handle.setframerate(44100)
            handle.writeframes(b"\x00\x00" * frames)
        return path

    return _make
