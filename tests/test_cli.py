import sqlite3

from typer.testing import CliRunner

from djlife import __version__, db
from djlife.cli import app

runner = CliRunner()


def test_version_flag() -> None:
    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0
    assert __version__ in result.stdout


def test_help_flag() -> None:
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "Usage" in result.stdout
    assert "report-cmd" not in result.stdout
    assert "apply-cmd" not in result.stdout
    assert "dedupe-cmd" not in result.stdout
    assert "versions-cmd" not in result.stdout
    assert "plan" in result.stdout
    assert "undo" in result.stdout
    assert "duplicates" in result.stdout
    assert "dedupe" in result.stdout
    assert "versions" in result.stdout
    assert "status" in result.stdout
    assert "relink" in result.stdout
    assert "ui" in result.stdout


def test_scan_command(tmp_path, make_wav) -> None:
    library = tmp_path / "lib"
    make_wav(library / "a.wav")

    db_path = tmp_path / "catalog.db"
    config = tmp_path / "djlife.toml"
    config.write_text(
        f'[library]\nroots = ["{library.as_posix()}"]\n'
        f'[catalog]\npath = "{db_path.as_posix()}"\n',
        encoding="utf-8",
    )

    result = runner.invoke(app, ["scan", "--config", str(config)])
    assert result.exit_code == 0

    conn = db.open_catalog(db_path)
    assert conn.execute("SELECT COUNT(*) FROM files").fetchone()[0] == 1
    assert conn.execute("SELECT COUNT(*) FROM tracks").fetchone()[0] == 1
    conn.close()


def test_scan_without_root_fails(tmp_path) -> None:
    config = tmp_path / "djlife.toml"
    config.write_text("[library]\nroots = []\n", encoding="utf-8")
    result = runner.invoke(app, ["scan", "--config", str(config)])
    assert result.exit_code == 1


def _scanned_library(tmp_path, make_wav):
    library = tmp_path / "lib"
    make_wav(library / "a.wav")
    db_path = tmp_path / "catalog.db"
    config = tmp_path / "djlife.toml"
    config.write_text(
        f'[library]\nroots = ["{library.as_posix()}"]\n'
        f'[catalog]\npath = "{db_path.as_posix()}"\n',
        encoding="utf-8",
    )
    assert runner.invoke(app, ["scan", "--config", str(config)]).exit_code == 0
    return config


def test_stats_command(tmp_path, make_wav) -> None:
    config = _scanned_library(tmp_path, make_wav)
    result = runner.invoke(app, ["stats", "--config", str(config)])
    assert result.exit_code == 0
    assert "Estatisticas" in result.stdout
    assert "Cobertura de tags" in result.stdout


def test_search_command(tmp_path, make_wav) -> None:
    config = _scanned_library(tmp_path, make_wav)
    result = runner.invoke(app, ["search", "a.wav", "--config", str(config)])
    assert result.exit_code == 0
    assert "a.wav" in result.stdout


def test_report_command(tmp_path, make_wav) -> None:
    config = _scanned_library(tmp_path, make_wav)
    out = tmp_path / "out.csv"
    result = runner.invoke(app, ["report", str(out), "--config", str(config)])
    assert result.exit_code == 0
    assert out.exists()
    assert "Exportadas 1 faixas" in result.stdout


def test_classify_command(tmp_path, make_wav) -> None:
    config = _scanned_library(tmp_path, make_wav)
    result = runner.invoke(app, ["classify", "--config", str(config)])
    assert result.exit_code == 0
    assert "Classify" in result.stdout
    assert "Generos na arvore" in result.stdout


def _classified_library(tmp_path, make_wav):
    library = tmp_path / "lib"
    make_wav(library / "a.wav")
    db_path = tmp_path / "catalog.db"
    out = tmp_path / "out"
    rules = tmp_path / "genres.local.yaml"
    rules.write_text(
        'version: "0.1.0"\nrules:\n'
        "  - name: lib\n    field: path\n    match: \"lib\"\n"
        '    genre: house\n    confidence: B\n',
        encoding="utf-8",
    )
    config = tmp_path / "djlife.toml"
    config.write_text(
        f'[library]\nroots = ["{library.as_posix()}"]\n'
        f'[catalog]\npath = "{db_path.as_posix()}"\n'
        f'[classification]\nlocal_taxonomy = "{rules.as_posix()}"\n'
        f'[files]\nstrategy = "hardlink"\ntarget = "{out.as_posix()}"\n',
        encoding="utf-8",
    )
    assert runner.invoke(app, ["scan", "--config", str(config)]).exit_code == 0
    assert runner.invoke(app, ["classify", "--config", str(config)]).exit_code == 0
    return config, out


def test_plan_command(tmp_path, make_wav) -> None:
    config, _ = _classified_library(tmp_path, make_wav)
    result = runner.invoke(app, ["plan", "--config", str(config)])
    assert result.exit_code == 0
    assert "Plano" in result.stdout
    assert "Prontos" in result.stdout


def test_plan_requires_target(tmp_path, make_wav) -> None:
    config = _scanned_library(tmp_path, make_wav)
    result = runner.invoke(app, ["plan", "--config", str(config)])
    assert result.exit_code == 1


def test_apply_and_undo_commands(tmp_path, make_wav) -> None:
    config, out = _classified_library(tmp_path, make_wav)

    applied = runner.invoke(app, ["apply", "--yes", "--config", str(config)])
    assert applied.exit_code == 0
    assert "Apply - lote" in applied.stdout
    assert list(out.rglob("*.wav"))

    undone = runner.invoke(app, ["undo", "--config", str(config)])
    assert undone.exit_code == 0
    assert "Undo - lote" in undone.stdout
    assert not list(out.rglob("*.wav"))


def test_undo_without_journal_fails(tmp_path, make_wav) -> None:
    config = _scanned_library(tmp_path, make_wav)
    result = runner.invoke(app, ["undo", "--config", str(config)])
    assert result.exit_code == 1


def _duplicate_library(tmp_path, make_wav):
    library = tmp_path / "lib"
    make_wav(library / "a.wav")
    make_wav(library / "sub" / "b.wav")
    db_path = tmp_path / "catalog.db"
    qroot = tmp_path / "q"
    config = tmp_path / "djlife.toml"
    config.write_text(
        f'[library]\nroots = ["{library.as_posix()}"]\n'
        f'[catalog]\npath = "{db_path.as_posix()}"\n'
        f'[files]\nquarantine_dir = "{qroot.as_posix()}"\n',
        encoding="utf-8",
    )
    assert runner.invoke(app, ["scan", "--config", str(config)]).exit_code == 0
    return config, qroot


def test_duplicates_command(tmp_path, make_wav) -> None:
    config, _ = _duplicate_library(tmp_path, make_wav)
    result = runner.invoke(app, ["duplicates", "--config", str(config)])
    assert result.exit_code == 0
    assert "Duplicatas" in result.stdout
    assert "hash" in result.stdout


def test_versions_command(tmp_path, make_wav) -> None:
    config = _scanned_library(tmp_path, make_wav)
    result = runner.invoke(app, ["versions", "--config", str(config)])
    assert result.exit_code == 0
    assert "Versoes" in result.stdout
    assert "Classificadas" in result.stdout


def test_dedupe_requires_quarantine_dir(tmp_path, make_wav) -> None:
    config = _scanned_library(tmp_path, make_wav)
    result = runner.invoke(app, ["dedupe", "--config", str(config)])
    assert result.exit_code == 1


def test_dedupe_plan_apply_and_undo(tmp_path, make_wav) -> None:
    config, qroot = _duplicate_library(tmp_path, make_wav)
    assert runner.invoke(app, ["duplicates", "--config", str(config)]).exit_code == 0

    plan = runner.invoke(app, ["dedupe", "--config", str(config)])
    assert plan.exit_code == 0
    assert "Quarentena" in plan.stdout
    assert not list(qroot.rglob("*.wav"))

    applied = runner.invoke(app, ["dedupe", "--apply", "--yes", "--config", str(config)])
    assert applied.exit_code == 0
    assert "Dedupe - lote" in applied.stdout
    assert list(qroot.rglob("*.wav"))

    undone = runner.invoke(app, ["undo", "--config", str(config)])
    assert undone.exit_code == 0
    assert "Undo - lote" in undone.stdout
    assert not list(qroot.rglob("*.wav"))


def _serato_library(tmp_path, make_wav):
    library = tmp_path / "lib"
    make_wav(library / "a.wav")
    db_path = tmp_path / "catalog.db"
    serato_db = tmp_path / "master.sqlite"
    conn = sqlite3.connect(serato_db)
    conn.execute("CREATE TABLE asset (portable_id TEXT, file_name TEXT, artist TEXT)")
    conn.execute("INSERT INTO asset VALUES (?, ?, ?)", (str(library / "a.wav"), "a.wav", "A"))
    conn.commit()
    conn.close()

    config = tmp_path / "djlife.toml"
    config.write_text(
        f'[library]\nroots = ["{library.as_posix()}"]\n'
        f'[catalog]\npath = "{db_path.as_posix()}"\n'
        f'[integrations]\nserato_db = "{serato_db.as_posix()}"\n',
        encoding="utf-8",
    )
    assert runner.invoke(app, ["scan", "--config", str(config)]).exit_code == 0
    return config, serato_db, library


def test_status_command(tmp_path, make_wav) -> None:
    config, _serato_db, _library = _serato_library(tmp_path, make_wav)

    result = runner.invoke(app, ["status", "--software", "serato", "--config", str(config)])

    assert result.exit_code == 0
    assert "Integridade das bibliotecas DJ" in result.stdout


def test_status_invalid_software(tmp_path, make_wav) -> None:
    config, _serato_db, _library = _serato_library(tmp_path, make_wav)

    result = runner.invoke(app, ["status", "--software", "traktor", "--config", str(config)])

    assert result.exit_code == 1


def test_relink_command_dry_run_and_apply(tmp_path, make_wav) -> None:
    config, serato_db, library = _serato_library(tmp_path, make_wav)
    db_path = tmp_path / "catalog.db"
    moved = tmp_path / "out" / "b.wav"
    moved.parent.mkdir(parents=True)
    (library / "a.wav").rename(moved)

    conn = db.open_catalog(db_path)
    conn.execute(
        "INSERT INTO journal(batch, created_at, op, strategy, src, dst, file_id, undone)"
        " VALUES ('b', 'now', 'move', 'move', ?, ?, NULL, 0)",
        (str(library / "a.wav"), str(moved)),
    )
    conn.commit()
    conn.close()

    dry = runner.invoke(app, ["relink", "--software", "serato", "--config", str(config)])
    assert dry.exit_code == 0
    assert "Relink - serato" in dry.stdout
    assert "Ajustes" in dry.stdout

    applied = runner.invoke(
        app, ["relink", "--software", "serato", "--apply", "--yes", "--config", str(config)]
    )
    assert applied.exit_code == 0
    assert "Atualizados" in applied.stdout

    conn = sqlite3.connect(serato_db)
    stored = conn.execute("SELECT portable_id FROM asset").fetchone()[0]
    conn.close()
    assert stored == str(moved)


def test_relink_without_journal(tmp_path, make_wav) -> None:
    config, _serato_db, _library = _serato_library(tmp_path, make_wav)

    result = runner.invoke(app, ["relink", "--software", "serato", "--config", str(config)])

    assert result.exit_code == 0
    assert "nada a relinkar" in result.stdout


def test_ui_command_starts_server(monkeypatch, tmp_path, make_wav) -> None:
    config = _scanned_library(tmp_path, make_wav)
    captured = {}

    def fake_serve(cfg, *, host, port, open_browser, on_ready):
        captured.update(host=host, port=port, open_browser=open_browser)
        on_ready("http://127.0.0.1:9090/")

    monkeypatch.setattr("djlife.cli.ui_server.serve", fake_serve)

    result = runner.invoke(app, ["ui", "--port", "9090", "--no-open", "--config", str(config)])

    assert result.exit_code == 0
    assert captured == {"host": "127.0.0.1", "port": 9090, "open_browser": False}
    assert "Interface djLife" in result.stdout
