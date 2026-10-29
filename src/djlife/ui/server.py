"""Servidor HTTP local (stdlib) que serve a interface cyberpunk do djLife.

Serve os assets embutidos em `ui/assets` e expoe endpoints JSON em `/api/*`.
Somente leitura: nunca escreve no catalogo nem no filesystem.
"""

from __future__ import annotations

import json
import threading
import webbrowser
from collections.abc import Callable
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from djlife import __version__
from djlife.config import Config
from djlife.ui import data

ASSETS_DIR = Path(__file__).with_name("assets")
CONTENT_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "application/javascript; charset=utf-8",
    ".svg": "image/svg+xml",
    ".json": "application/json; charset=utf-8",
}
DEFAULT_LIMIT = 200
MAX_LIMIT = 1000


def _limit(query: dict[str, list[str]], default: int = DEFAULT_LIMIT) -> int:
    raw = query.get("limit", [""])[0]
    try:
        value = int(raw)
    except ValueError:
        return default
    return max(1, min(value, MAX_LIMIT))


def resolve_asset(name: str) -> Path | None:
    """Resolve um asset dentro de `ui/assets`, bloqueando travessia de diretorio."""
    candidate = (ASSETS_DIR / name).resolve()
    if ASSETS_DIR.resolve() not in candidate.parents or not candidate.is_file():
        return None
    return candidate


class _Handler(BaseHTTPRequestHandler):
    server_version = "djlife-ui"

    cfg: Config

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
        cfg = self.cfg
        try:
            if endpoint == "overview":
                payload = data.overview(cfg)
            elif endpoint == "tracks":
                term = query.get("q", [""])[0]
                payload = {"tracks": data.tracks(cfg, term, limit=_limit(query))}
            elif endpoint == "duplicates":
                payload = data.duplicates(cfg, limit=_limit(query, 50))
            elif endpoint == "versions":
                payload = data.versions(cfg, limit=_limit(query, 50))
            elif endpoint == "integrations":
                payload = data.integrations(cfg)
            elif endpoint == "capabilities":
                payload = data.capabilities()
            elif endpoint == "version":
                payload = {"name": "djlife", "version": __version__}
            else:
                self._send_json({"error": f"endpoint desconhecido: {endpoint}"}, status=404)
                return
        except data.CatalogUnavailable as exc:
            self._send_json({"error": str(exc)}, status=503)
            return
        self._send_json(payload)


def build_handler(cfg: Config) -> type[_Handler]:
    """Cria a classe de handler ligada a configuracao informada."""
    return type("_BoundHandler", (_Handler,), {"cfg": cfg})


def build_server(
    cfg: Config, *, host: str = "127.0.0.1", port: int = 8765
) -> ThreadingHTTPServer:
    """Instancia o servidor (sem iniciar o loop)."""
    return ThreadingHTTPServer((host, port), build_handler(cfg))


def serve(
    cfg: Config,
    *,
    host: str = "127.0.0.1",
    port: int = 8765,
    open_browser: bool = True,
    on_ready: Callable[[str], None] | None = None,
) -> None:
    """Sobe o servidor local e bloqueia ate KeyboardInterrupt."""
    httpd = build_server(cfg, host=host, port=port)
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
