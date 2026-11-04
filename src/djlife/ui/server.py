"""Servidor HTTP local (stdlib) que serve a interface Tech-Noir do djLife.

Serve os assets embutidos em `ui/assets` e expoe endpoints JSON em `/api/*`.
O catalogo permanece somente leitura para consulta; as unicas escritas ocorrem
em `/api/setup/*` (pasta raiz do primeiro acesso), `/api/organize/*`
(classificacao, plano e aplicacao com journal/undo) e `/api/premium/*`
(download online e curadoria assistida), todas gated por token de administracao,
bloqueio de mesma origem (CSRF) e bind em 127.0.0.1. `/api/admin/*` cuida do
registro local de licencas.
"""

from __future__ import annotations

import json
import threading
import webbrowser
from collections.abc import Callable
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, cast
from urllib.parse import parse_qs, urlparse

from djlife import __version__, admin, registry
from djlife import license as license_mod
from djlife.config import Config
from djlife.ui import curation, data, download, jobs, organize, setup

ASSETS_DIR = Path(__file__).with_name("assets")
CONTENT_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "application/javascript; charset=utf-8",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".ico": "image/x-icon",
    ".svg": "image/svg+xml",
    ".json": "application/json; charset=utf-8",
}
DEFAULT_LIMIT = 200
MAX_LIMIT = 1000
DEFAULT_CONFIG_PATH = Path("djlife.toml")


def _limit(query: dict[str, list[str]], default: int = DEFAULT_LIMIT) -> int:
    raw = query.get("limit", [""])[0]
    try:
        value = int(raw)
    except ValueError:
        return default
    return max(1, min(value, MAX_LIMIT))


def _opt_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _opt_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _as_list(value: Any) -> list[str] | None:
    if value is None:
        return None
    if isinstance(value, str):
        items = [part.strip() for part in value.replace(",", " ").split()]
    elif isinstance(value, (list, tuple)):
        items = [str(part).strip() for part in value]
    else:
        return None
    filtered = [item for item in items if item]
    return filtered or None


def _as_int_list(value: Any) -> list[int] | None:
    """Converte uma lista de ids; distingue ausente (None) de vazia ([])."""
    if not isinstance(value, (list, tuple)):
        return None
    result: list[int] = []
    for item in value:
        try:
            result.append(int(item))
        except (TypeError, ValueError):
            continue
    return result


def resolve_asset(name: str) -> Path | None:
    """Resolve um asset dentro de `ui/assets`, bloqueando travessia de diretorio."""
    candidate = (ASSETS_DIR / name).resolve()
    if ASSETS_DIR.resolve() not in candidate.parents or not candidate.is_file():
        return None
    return candidate


class _Server(ThreadingHTTPServer):
    """Servidor com configuracao mutavel (setup do primeiro acesso) e jobs longos."""

    cfg: Config
    config_path: Path
    scan_job: setup.ScanJob | None
    jobs: dict[str, jobs.TaskJob]

    def __init__(
        self,
        address: tuple[str, int],
        handler: type[BaseHTTPRequestHandler],
        *,
        cfg: Config,
        config_path: Path,
    ) -> None:
        super().__init__(address, handler)
        self.cfg = cfg
        self.config_path = config_path
        self.scan_job = None
        self.jobs = {}


class _Handler(BaseHTTPRequestHandler):
    server_version = "djlife-ui"

    cfg: Config = Config()

    @property
    def config(self) -> Config:
        server = self.server
        return server.cfg if isinstance(server, _Server) else self.cfg

    @property
    def config_path(self) -> Path:
        server = self.server
        return server.config_path if isinstance(server, _Server) else DEFAULT_CONFIG_PATH

    @property
    def scan_job(self) -> setup.ScanJob | None:
        server = self.server
        return server.scan_job if isinstance(server, _Server) else None

    @property
    def jobs(self) -> dict[str, jobs.TaskJob]:
        server = self.server
        return server.jobs if isinstance(server, _Server) else {}

    def log_message(self, format: str, *args: Any) -> None:
        return

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        route = parsed.path
        if route in ("/", "/index.html"):
            self._send_asset("index.html")
        elif route.startswith("/assets/"):
            self._send_asset(route[len("/assets/") :])
        elif route.startswith("/api/"):
            self._send_api(route[len("/api/") :], parse_qs(parsed.query))
        else:
            self._send_json({"error": "rota nao encontrada"}, status=404)

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        route = parsed.path
        if route.startswith("/api/setup/"):
            self._post_setup(route[len("/api/setup/") :])
            return
        if route.startswith("/api/organize/"):
            self._post_organize(route[len("/api/organize/") :])
            return
        if route.startswith("/api/premium/"):
            self._post_premium(route[len("/api/premium/") :])
            return
        if not route.startswith("/api/admin/"):
            self._send_json({"error": "rota nao encontrada"}, status=404)
            return
        endpoint = route[len("/api/admin/") :]
        try:
            body = self._read_json_body()
        except ValueError as exc:
            self._send_json({"error": str(exc)}, status=400)
            return
        token = self.headers.get("X-Admin-Token", "") or str(body.get("token", ""))
        try:
            admin.require_token(self.config, token)
            payload = self._admin_action(endpoint, body)
        except admin.AdminUnavailable as exc:
            self._send_json({"error": str(exc)}, status=403)
            return
        except (registry.RegistryError, license_mod.LicenseError, ValueError) as exc:
            self._send_json({"error": str(exc)}, status=400)
            return
        if payload is None:
            self._send_json({"error": f"endpoint admin desconhecido: {endpoint}"}, status=404)
            return
        self._send_json(payload)

    def _same_origin(self) -> bool:
        """Bloqueia POST cross-origin (CSRF) quando o navegador envia `Origin`."""
        origin = self.headers.get("Origin")
        if not origin:
            return True
        host = self.headers.get("Host", "")
        return origin in {f"http://{host}", f"https://{host}"}

    def _post_setup(self, endpoint: str) -> None:
        if not self._same_origin():
            self._send_json({"error": "origem nao permitida"}, status=403)
            return
        try:
            body = self._read_json_body()
        except ValueError as exc:
            self._send_json({"error": str(exc)}, status=400)
            return
        try:
            if endpoint == "root":
                path = str(body.get("path", "")).strip()
                if not path:
                    raise setup.SetupError("informe a pasta raiz")
                cfg = setup.save_root(self.config_path, path)
                cast(_Server, self.server).cfg = cfg
                payload = setup.state(cfg, self.config_path)
            elif endpoint == "files":
                admin.require_token(self.config, self.headers.get("X-Admin-Token", ""))
                cfg = setup.save_files(
                    self.config_path,
                    target=str(body.get("target", "")),
                    strategy=str(body.get("strategy", "")),
                )
                cast(_Server, self.server).cfg = cfg
                payload = setup.files_state(cfg)
            elif endpoint == "scan":
                server = cast(_Server, self.server)
                if server.scan_job is None or server.scan_job.status != "running":
                    server.scan_job = setup.start_scan(self.config)
                payload = server.scan_job.snapshot()
            else:
                self._send_json({"error": f"endpoint desconhecido: {endpoint}"}, status=404)
                return
        except setup.SetupError as exc:
            self._send_json({"error": str(exc)}, status=400)
            return
        except admin.AdminUnavailable as exc:
            self._send_json({"error": str(exc)}, status=403)
            return
        except ValueError as exc:
            self._send_json({"error": str(exc)}, status=400)
            return
        self._send_json(payload)

    def _post_organize(self, endpoint: str) -> None:
        if not self._same_origin():
            self._send_json({"error": "origem nao permitida"}, status=403)
            return
        try:
            body = self._read_json_body()
        except ValueError as exc:
            self._send_json({"error": str(exc)}, status=400)
            return
        token = self.headers.get("X-Admin-Token", "") or str(body.get("token", ""))
        try:
            admin.require_token(self.config, token)
            payload = self._organize_action(endpoint, body)
        except admin.AdminUnavailable as exc:
            self._send_json({"error": str(exc)}, status=403)
            return
        except (organize.OrganizeError, setup.SetupError) as exc:
            self._send_json({"error": str(exc)}, status=400)
            return
        if payload is None:
            self._send_json(
                {"error": f"endpoint de organizacao desconhecido: {endpoint}"}, status=404
            )
            return
        self._send_json(payload)

    def _organize_action(self, endpoint: str, body: dict[str, Any]) -> dict[str, Any] | None:
        cfg = self.config
        server = cast(_Server, self.server)
        if endpoint == "scan":
            job = server.scan_job
            if job is None or job.status != "running":
                job = setup.start_scan(cfg)
                server.scan_job = job
            return job.snapshot()
        if endpoint == "classify":
            task = server.jobs.get("classify")
            if task is None or task.status != "running":
                task = organize.start_classify(cfg)
                server.jobs["classify"] = task
            return task.snapshot()
        if endpoint == "apply":
            task = server.jobs.get("apply")
            if task is None or task.status != "running":
                task = organize.start_apply(
                    cfg,
                    track_ids=_as_int_list(body.get("track_ids")),
                    write_tags=bool(body.get("write_tags", True)),
                )
                server.jobs["apply"] = task
            return task.snapshot()
        if endpoint == "undo":
            task = server.jobs.get("undo")
            if task is None or task.status != "running":
                task = organize.start_undo(cfg, batch=_opt_str(body.get("batch")))
                server.jobs["undo"] = task
            return task.snapshot()
        return None

    def _post_premium(self, endpoint: str) -> None:
        if not self._same_origin():
            self._send_json({"error": "origem nao permitida"}, status=403)
            return
        try:
            body = self._read_json_body()
        except ValueError as exc:
            self._send_json({"error": str(exc)}, status=400)
            return
        token = self.headers.get("X-Admin-Token", "") or str(body.get("token", ""))
        try:
            admin.require_token(self.config, token)
            payload = self._premium_action(endpoint, body)
        except admin.AdminUnavailable as exc:
            self._send_json({"error": str(exc)}, status=403)
            return
        except download.DownloadUnavailable as exc:
            self._send_json({"error": str(exc)}, status=403)
            return
        except curation.CurationUnavailable as exc:
            self._send_json({"error": str(exc)}, status=403)
            return
        except (download.DownloadError, curation.CurationError) as exc:
            self._send_json({"error": str(exc)}, status=400)
            return
        if payload is None:
            self._send_json({"error": f"endpoint premium desconhecido: {endpoint}"}, status=404)
            return
        self._send_json(payload)

    def _premium_action(self, endpoint: str, body: dict[str, Any]) -> dict[str, Any] | None:
        cfg = self.config
        server = cast(_Server, self.server)
        if endpoint == "probe":
            task = server.jobs.get("probe")
            if task is None or task.status != "running":
                task = download.start_probe(cfg, body.get("urls"))
                server.jobs["probe"] = task
            return task.snapshot()
        if endpoint == "download":
            task = server.jobs.get("download")
            if task is None or task.status != "running":
                task = download.start_download(
                    cfg,
                    body.get("urls"),
                    target=body.get("target"),
                    audio_format=body.get("format"),
                )
                server.jobs["download"] = task
            return task.snapshot()
        if endpoint == "curation":
            return curation.decide(
                cfg,
                body.get("track_id"),
                body.get("genre_id"),
                operator=_opt_str(body.get("operator")),
            )
        return None

    def _job_snapshot(self, task: str) -> dict[str, Any]:
        if task == "scan":
            scan = self.scan_job
            return scan.snapshot() if scan is not None else {"status": "idle"}
        job = self.jobs.get(task)
        return job.snapshot() if job is not None else jobs.idle_snapshot(task)

    def _admin_action(self, endpoint: str, body: dict[str, Any]) -> dict[str, Any] | None:
        cfg = self.config
        passphrase = str(body["passphrase"]) if body.get("passphrase") else None
        if endpoint == "issue":
            return admin.issue(
                cfg,
                customer_id=str(body.get("customer_id", "")),
                plan=str(body.get("plan", "lifetime")),
                features=_as_list(body.get("features")),
                machine_hash=_opt_str(body.get("machine_hash")),
                bind_current_machine=bool(body.get("bind_current_machine")),
                days=_opt_int(body.get("days")),
                expires=_opt_str(body.get("expires")),
                issuer=_opt_str(body.get("issuer")),
                output=_opt_str(body.get("output")),
                passphrase=passphrase,
            )
        if endpoint == "renew":
            return admin.renew(
                cfg,
                str(body.get("id", "")),
                plan=_opt_str(body.get("plan")),
                features=_as_list(body.get("features")),
                days=_opt_int(body.get("days")),
                expires=_opt_str(body.get("expires")),
                issuer=_opt_str(body.get("issuer")),
                passphrase=passphrase,
            )
        if endpoint == "revoke":
            return admin.revoke(
                cfg,
                str(body.get("id", "")),
                reason=_opt_str(body.get("reason")),
            )
        return None

    def _read_json_body(self) -> dict[str, Any]:
        raw_length = self.headers.get("Content-Length", "0") or "0"
        try:
            length = int(raw_length)
        except ValueError:
            length = 0
        if length <= 0:
            return {}
        try:
            data = json.loads(self.rfile.read(length).decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError("corpo JSON invalido") from exc
        if not isinstance(data, dict):
            raise ValueError("corpo JSON deve ser um objeto")
        return data

    def _send_asset(self, name: str) -> None:
        candidate = resolve_asset(name)
        if candidate is None:
            self._send_json({"error": "asset nao encontrado"}, status=404)
            return
        payload = candidate.read_bytes()
        content_type = CONTENT_TYPES.get(candidate.suffix, "application/octet-stream")
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(payload)

    def _send_json(self, payload: dict[str, Any], status: int = 200) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", CONTENT_TYPES[".json"])
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _send_api(self, endpoint: str, query: dict[str, list[str]]) -> None:
        cfg = self.config
        try:
            if endpoint == "overview":
                payload = data.overview(cfg)
            elif endpoint == "setup/status":
                payload = setup.state(cfg, self.config_path)
            elif endpoint == "setup/list":
                payload = setup.list_directory(query.get("path", [""])[0])
            elif endpoint == "setup/scan":
                job = self.scan_job
                payload = job.snapshot() if job is not None else {"status": "idle"}
            elif endpoint == "tracks":
                term = query.get("q", [""])[0]
                payload = {"tracks": data.tracks(cfg, term, limit=_limit(query))}
            elif endpoint == "duplicates":
                payload = data.duplicates(cfg, limit=_limit(query, 50))
            elif endpoint == "versions":
                payload = data.versions(cfg, limit=_limit(query, 50))
            elif endpoint == "integrations":
                payload = data.integrations(cfg)
            elif endpoint == "organize/status":
                payload = organize.status(cfg)
            elif endpoint == "organize/plan":
                payload = organize.plan_payload(cfg)
            elif endpoint == "organize/history":
                payload = organize.history(cfg, limit=_limit(query, 20))
            elif endpoint == "organize/job":
                payload = self._job_snapshot(query.get("task", [""])[0])
            elif endpoint == "premium/status":
                payload = download.status(cfg)
            elif endpoint == "premium/job":
                payload = self._job_snapshot(query.get("task", [""])[0])
            elif endpoint == "premium/curation":
                payload = curation.queue_payload(cfg)
            elif endpoint == "capabilities":
                payload = data.capabilities(cfg)
            elif endpoint == "version":
                payload = {"name": "djlife", "version": __version__}
            elif endpoint == "admin/status":
                payload = admin.status_public(cfg)
            elif endpoint == "admin/licenses":
                token = self.headers.get("X-Admin-Token", "")
                try:
                    admin.require_token(cfg, token)
                except admin.AdminUnavailable as exc:
                    self._send_json({"error": str(exc)}, status=403)
                    return
                payload = {"status": admin.status_detail(cfg), **admin.licenses_payload(cfg)}
            else:
                self._send_json({"error": f"endpoint desconhecido: {endpoint}"}, status=404)
                return
        except data.CatalogUnavailable as exc:
            self._send_json({"error": str(exc)}, status=503)
            return
        except setup.SetupError as exc:
            self._send_json({"error": str(exc)}, status=400)
            return
        except organize.OrganizeError as exc:
            self._send_json({"error": str(exc)}, status=400)
            return
        except curation.CurationError as exc:
            self._send_json({"error": str(exc)}, status=400)
            return
        except registry.RegistryError as exc:
            self._send_json({"error": str(exc)}, status=500)
            return
        self._send_json(payload)


def build_handler(cfg: Config) -> type[_Handler]:
    """Cria a classe de handler ligada a configuracao informada."""
    return type("_BoundHandler", (_Handler,), {"cfg": cfg})


def build_server(
    cfg: Config,
    *,
    host: str = "127.0.0.1",
    port: int = 8765,
    config_path: Path | str = DEFAULT_CONFIG_PATH,
) -> _Server:
    """Instancia o servidor (sem iniciar o loop)."""
    return _Server((host, port), build_handler(cfg), cfg=cfg, config_path=Path(config_path))


def serve(
    cfg: Config,
    *,
    host: str = "127.0.0.1",
    port: int = 8765,
    open_browser: bool = True,
    config_path: Path | str = DEFAULT_CONFIG_PATH,
    on_ready: Callable[[str], None] | None = None,
) -> None:
    """Sobe o servidor local e bloqueia ate KeyboardInterrupt."""
    httpd = build_server(cfg, host=host, port=port, config_path=config_path)
    bound_host = str(httpd.server_address[0])
    bound_port = int(httpd.server_address[1])
    url = f"http://{bound_host}:{bound_port}/"
    if on_ready is not None:
        on_ready(url)
    if open_browser:
        threading.Timer(0.4, webbrowser.open, args=(url,)).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()
