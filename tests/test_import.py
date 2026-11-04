from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from djlife import importer, premium
from djlife import license as license_mod
from djlife.cli import app

runner = CliRunner()


def _licensed_config(tmp_path: Path) -> Path:
    private_key = tmp_path / "private.pem"
    public_key = tmp_path / "public.pem"
    license_file = tmp_path / "license.json"
    license_mod.generate_keypair(private_key, public_key)
    license_mod.issue_license(
        private_key,
        license_file,
        customer_id="cliente-import",
        plan="lifetime",
        features=(premium.YTDLP_IMPORT_FEATURE,),
        machine_hash_value=license_mod.machine_hash(),
        expires_at=None,
    )
    config = tmp_path / "djlife.toml"
    config.write_text(
        f'[license]\npublic_key = "{public_key.as_posix()}"\n'
        f'license_file = "{license_file.as_posix()}"\n',
        encoding="utf-8",
    )
    return config


def test_import_requires_license(tmp_path) -> None:
    config = tmp_path / "djlife.toml"
    config.write_text(
        f'[license]\npublic_key = "{(tmp_path / "none.pem").as_posix()}"\n'
        f'license_file = "{(tmp_path / "none.json").as_posix()}"\n',
        encoding="utf-8",
    )

    result = runner.invoke(app, ["import", "https://example.com/x", "--config", str(config)])

    assert result.exit_code == 1
    assert "premium" in result.stdout.lower()


def test_import_dry_run_lists_candidates(tmp_path, monkeypatch) -> None:
    config = _licensed_config(tmp_path)

    def fake_probe(urls):
        return [
            importer.ImportCandidate(
                url=urls[0], title="Track", uploader="Canal", duration=185.0, ext="webm"
            )
        ]

    monkeypatch.setattr(importer, "probe", fake_probe)

    result = runner.invoke(app, ["import", "https://example.com/x", "--config", str(config)])

    assert result.exit_code == 0
    assert "Track" in result.stdout
    assert "Canal" in result.stdout
    assert "Dry-run" in result.stdout


def test_import_apply_downloads(tmp_path, monkeypatch) -> None:
    config = _licensed_config(tmp_path)
    out = tmp_path / "downloads"

    def fake_download(urls, *, target_dir, audio_format):
        path = Path(target_dir) / "Track [id].webm"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"x")
        return [importer.DownloadOutcome(urls[0], path, True, "ok")]

    monkeypatch.setattr(importer, "download", fake_download)

    result = runner.invoke(
        app,
        ["import", "https://example.com/x", "--apply", "--out", str(out), "--config", str(config)],
    )

    assert result.exit_code == 0
    assert "djlife scan" in result.stdout


def test_import_without_extra_reports_hint(tmp_path, monkeypatch) -> None:
    config = _licensed_config(tmp_path)

    def boom():
        raise importer.ImportUnavailable("yt-dlp nao esta instalado.")

    monkeypatch.setattr(importer, "_ytdlp", boom)

    result = runner.invoke(app, ["import", "https://example.com/x", "--config", str(config)])

    assert result.exit_code == 1
    assert "yt-dlp" in result.stdout


def test_probe_raises_when_extra_missing(monkeypatch) -> None:
    def boom():
        raise importer.ImportUnavailable("sem yt-dlp")

    monkeypatch.setattr(importer, "_ytdlp", boom)

    with pytest.raises(importer.ImportUnavailable):
        importer.probe(["https://example.com/x"])
