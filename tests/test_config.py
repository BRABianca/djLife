from pathlib import Path

import pytest

from djlife import config


def test_defaults_when_file_missing():
    cfg = config.load_config(Path("nao_existe.toml"))
    assert cfg.files.strategy == "hardlink"
    assert "mp3" in cfg.library.extensions
    assert cfg.integrations.dj_software == ()


def test_load_from_toml(tmp_path):
    path = tmp_path / "djlife.toml"
    path.write_text(
        '[library]\nroots = ["D:/Music"]\n'
        '[files]\nstrategy = "move"\n'
        '[integrations]\ndj_software = ["rekordbox", "serato"]\n',
        encoding="utf-8",
    )
    cfg = config.load_config(path)
    assert cfg.files.strategy == "move"
    assert cfg.library.roots == (Path("D:/Music"),)
    assert cfg.integrations.dj_software == ("rekordbox", "serato")


def test_invalid_strategy_rejected(tmp_path):
    path = tmp_path / "djlife.toml"
    path.write_text('[files]\nstrategy = "explodir"\n', encoding="utf-8")
    with pytest.raises(ValueError, match="strategy"):
        config.load_config(path)


def test_extensions_normalized(tmp_path):
    path = tmp_path / "djlife.toml"
    path.write_text('[library]\nextensions = [".MP3", "Flac"]\n', encoding="utf-8")
    assert config.load_config(path).library.extensions == ("mp3", "flac")
