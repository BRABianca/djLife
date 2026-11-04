import json
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

import pytest

from djlife import config as config_mod
from djlife.ui import server, setup


def _get(url: str) -> tuple[int, bytes]:
    with urllib.request.urlopen(url, timeout=5) as response:
        return response.status, response.read()


def _post(url: str, payload: dict, headers: dict | None = None) -> tuple[int, bytes]:
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        method="POST",
        headers={"Content-Type": "application/json", **(headers or {})},
    )
    with urllib.request.urlopen(request, timeout=5) as response:
        return response.status, response.read()


def test_update_library_roots_preserves_other_blocks(tmp_path) -> None:
    config_file = tmp_path / "djlife.toml"
    config_file.write_text(
        "# comentario\n"
        "schema_version = 4\n\n"
        '[library]\nroots = ["C:/old"]\nfollow_symlinks = true\n\n'
        '[license]\nadmin_token = "abc"\n',
        encoding="utf-8",
    )

    config_mod.update_library_roots(config_file, ["D:/Music", "E:/Sets"])

    text = config_file.read_text(encoding="utf-8")
    assert 'roots = ["D:/Music", "E:/Sets"]' in text
    assert "# comentario" in text
    assert "follow_symlinks = true" in text
    assert 'admin_token = "abc"' in text
    assert "C:/old" not in text
    assert config_mod.load_config(config_file).library.roots == (
        Path("D:/Music"),
        Path("E:/Sets"),
    )


def test_update_library_roots_creates_file(tmp_path) -> None:
    config_file = tmp_path / "djlife.toml"
    root = tmp_path / "Music"

    config_mod.update_library_roots(config_file, [str(root)])

    assert config_file.exists()
    assert config_mod.load_config(config_file).library.roots == (root,)


def test_update_library_roots_inserts_into_existing_section(tmp_path) -> None:
    config_file = tmp_path / "djlife.toml"
    config_file.write_text(
        '[library]\nfollow_symlinks = false\n\n[catalog]\npath = "/tmp/x.db"\n',
        encoding="utf-8",
    )

    config_mod.update_library_roots(config_file, ["/music"])

    text = config_file.read_text(encoding="utf-8")
    assert 'roots = ["/music"]' in text
    assert "follow_symlinks = false" in text
    assert config_mod.load_config(config_file).library.roots == (Path("/music"),)


def test_setup_state_and_listing(tmp_path) -> None:
    root = tmp_path / "Music"
    (root / "house").mkdir(parents=True)
    (root / "techno").mkdir()
    (root / ".hidden").mkdir()
    config_file = tmp_path / "djlife.toml"

    state = setup.state(config_mod.load_config(config_file), config_file)
    assert state["configured"] is False
    assert state["places"]

    listing = setup.list_directory(str(root))
    assert listing["path"] == str(root)
    assert [item["name"] for item in listing["dirs"]] == ["house", "techno"]


def test_setup_save_root_writes_config(tmp_path) -> None:
    root = tmp_path / "Music"
    root.mkdir()
    config_file = tmp_path / "djlife.toml"

    saved = setup.save_root(config_file, str(root))

    assert saved.library.roots == (root,)
    assert setup.state(saved, config_file)["configured"] is True


def test_setup_rejects_invalid_paths(tmp_path) -> None:
    config_file = tmp_path / "djlife.toml"

    with pytest.raises(setup.SetupError):
        setup.save_root(config_file, str(tmp_path / "nope"))
    with pytest.raises(setup.SetupError):
        setup.list_directory(str(tmp_path / "nope"))
    with pytest.raises(setup.SetupError):
        setup.start_scan(config_mod.load_config(config_file))


def test_server_setup_flow(tmp_path, make_wav) -> None:
    library = tmp_path / "lib"
    make_wav(library / "a.wav")
    db_path = tmp_path / "catalog.db"
    config_file = tmp_path / "djlife.toml"
    config_file.write_text(f'[catalog]\npath = "{db_path.as_posix()}"\n', encoding="utf-8")
    cfg = config_mod.load_config(config_file)

    httpd = server.build_server(cfg, host="127.0.0.1", port=0, config_path=config_file)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    host, port = httpd.server_address[:2]
    base = f"http://{host}:{port}"
    try:
        _, body = _get(f"{base}/api/setup/status")
        assert json.loads(body)["configured"] is False

        query = urllib.parse.quote(str(library))
        _, body = _get(f"{base}/api/setup/list?path={query}")
        assert json.loads(body)["dirs"] == []

        _, body = _post(f"{base}/api/setup/root", {"path": str(library)})
        assert json.loads(body)["configured"] is True
        assert config_mod.load_config(config_file).library.roots == (library,)

        _, body = _post(f"{base}/api/setup/scan", {})
        assert json.loads(body)["status"] in {"running", "done"}

        payload = {"status": "running"}
        for _ in range(60):
            _, body = _get(f"{base}/api/setup/scan")
            payload = json.loads(body)
            if payload["status"] != "running":
                break
            time.sleep(0.1)
        assert payload["status"] == "done"
        assert payload["seen"] == 1
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join(timeout=5)


def test_server_setup_rejects_blank_root(tmp_path) -> None:
    config_file = tmp_path / "djlife.toml"
    cfg = config_mod.load_config(config_file)

    httpd = server.build_server(cfg, host="127.0.0.1", port=0, config_path=config_file)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    host, port = httpd.server_address[:2]
    base = f"http://{host}:{port}"
    try:
        with pytest.raises(urllib.error.HTTPError) as error:
            _post(f"{base}/api/setup/root", {"path": "  "})
        assert error.value.code == 400
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join(timeout=5)


def test_update_files_settings_preserves_other_blocks(tmp_path) -> None:
    config_file = tmp_path / "djlife.toml"
    config_file.write_text(
        '[library]\nroots = ["C:/Music"]\n\n'
        '[files]\nstrategy = "hardlink"\ntarget = "C:/old"\n'
        'template = "{genre}/{artist}"\n\n'
        '[license]\nadmin_token = "abc"\n',
        encoding="utf-8",
    )

    config_mod.update_files_settings(config_file, target="D:/Out", strategy="move")

    text = config_file.read_text(encoding="utf-8")
    assert 'strategy = "move"' in text
    assert 'target = "D:/Out"' in text
    assert 'template = "{genre}/{artist}"' in text
    assert 'roots = ["C:/Music"]' in text
    assert 'admin_token = "abc"' in text
    assert "C:/old" not in text
    loaded = config_mod.load_config(config_file)
    assert loaded.files.target == Path("D:/Out")
    assert loaded.files.strategy == "move"


def test_update_files_settings_creates_section(tmp_path) -> None:
    config_file = tmp_path / "djlife.toml"
    config_file.write_text('[library]\nroots = ["C:/Music"]\n', encoding="utf-8")

    config_mod.update_files_settings(config_file, target="D:/Out", strategy="hardlink")

    text = config_file.read_text(encoding="utf-8")
    assert "[files]" in text
    assert 'roots = ["C:/Music"]' in text
    loaded = config_mod.load_config(config_file)
    assert loaded.files.target == Path("D:/Out")
    assert loaded.files.strategy == "hardlink"


def test_update_files_settings_rejects_invalid_strategy(tmp_path) -> None:
    config_file = tmp_path / "djlife.toml"

    with pytest.raises(ValueError):
        config_mod.update_files_settings(config_file, target="D:/Out", strategy="nope")


def test_setup_save_files_writes_config(tmp_path) -> None:
    config_file = tmp_path / "djlife.toml"
    destination = tmp_path / "out"

    saved = setup.save_files(config_file, target=str(destination), strategy="move")

    assert saved.files.target == destination
    assert saved.files.strategy == "move"
    state = setup.files_state(saved)
    assert state["target"] == str(destination)
    assert state["strategy"] == "move"
    assert "hardlink" in state["strategies"]


def test_setup_save_files_rejects_invalid_target(tmp_path) -> None:
    config_file = tmp_path / "djlife.toml"
    file_target = tmp_path / "not-a-dir"
    file_target.write_text("x", encoding="utf-8")

    with pytest.raises(setup.SetupError):
        setup.save_files(config_file, target="  ", strategy="hardlink")
    with pytest.raises(setup.SetupError):
        setup.save_files(config_file, target=str(tmp_path / "out"), strategy="nope")
    with pytest.raises(setup.SetupError):
        setup.save_files(config_file, target=str(file_target), strategy="hardlink")


def test_server_setup_files_requires_token(tmp_path) -> None:
    config_file = tmp_path / "djlife.toml"
    config_file.write_text('[license]\nadmin_token = "abc"\n', encoding="utf-8")
    cfg = config_mod.load_config(config_file)
    payload = {"target": str(tmp_path / "out"), "strategy": "move"}

    httpd = server.build_server(cfg, host="127.0.0.1", port=0, config_path=config_file)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    host, port = httpd.server_address[:2]
    base = f"http://{host}:{port}"
    try:
        with pytest.raises(urllib.error.HTTPError) as error:
            _post(f"{base}/api/setup/files", payload)
        assert error.value.code == 403

        _, body = _post(f"{base}/api/setup/files", payload, {"X-Admin-Token": "abc"})
        assert json.loads(body)["strategy"] == "move"
        assert config_mod.load_config(config_file).files.strategy == "move"
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join(timeout=5)
