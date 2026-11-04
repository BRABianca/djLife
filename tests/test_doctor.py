from djlife import db, doctor
from djlife.config import CatalogConfig, Config, FilesConfig, LibraryConfig


def test_run_flags_missing_catalog(tmp_path) -> None:
    cfg = Config(catalog=CatalogConfig(path=tmp_path / "sem.db"))

    checks = doctor.run(cfg)

    catalog = next(check for check in checks if check.name == "catalogo")
    assert catalog.status == doctor.FAIL


def test_run_reports_healthy_catalog(tmp_path) -> None:
    db_path = tmp_path / "catalog.db"
    conn = db.open_catalog(db_path)
    conn.close()

    cfg = Config(catalog=CatalogConfig(path=db_path))
    checks = {check.name: check for check in doctor.run(cfg)}

    assert checks["catalogo"].status == doctor.OK
    assert checks["schema"].status == doctor.OK
    assert checks["journal_mode"].status == doctor.OK
    assert checks["foreign_keys"].status == doctor.OK
    assert checks["integridade"].status == doctor.OK


def test_run_lists_optional_extras() -> None:
    names = {check.name for check in doctor.run(Config())}

    assert "extra ml: torch" in names
    assert "extra muq: muq" in names
    assert "binario ffmpeg" in names


def test_run_warns_missing_root(tmp_path) -> None:
    root = tmp_path / "biblioteca"
    checks = doctor.run(Config(library=LibraryConfig(roots=(root,))))

    missing = next(check for check in checks if check.name == f"raiz: {root}")
    assert missing.status == doctor.WARN


def test_run_ok_for_existing_target(tmp_path) -> None:
    target = tmp_path / "out"
    target.mkdir()
    checks = doctor.run(Config(files=FilesConfig(target=target)))

    check = next(item for item in checks if item.name == "files.target")
    assert check.status == doctor.OK
