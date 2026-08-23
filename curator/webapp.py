from __future__ import annotations

import base64
import hmac
import json
import threading
from datetime import datetime
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib.resources import files
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

from .review import create_review_album


class FeedbackStore:
    def __init__(self, path: Path) -> None:
        self.path = path
        self._lock = threading.Lock()

    def read(self) -> dict[str, Any]:
        if not self.path.exists():
            return {"version": 1, "events": {}}
        value = json.loads(self.path.read_text(encoding="utf-8"))
        if not isinstance(value, dict) or not isinstance(value.get("events"), dict):
            raise ValueError("Feedback JSON is invalid")
        return value

    def set_status(self, event_id: str, status: str, album_id: str | None = None) -> dict[str, Any]:
        if status not in {"pending", "held", "review_album_created"}:
            raise ValueError("Unsupported feedback status")
        with self._lock:
            value = self.read()
            row = {"status": status, "updated_at": datetime.now().astimezone().isoformat()}
            if album_id:
                row["album_id"] = album_id
            value["events"][event_id] = row
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temporary = self.path.with_suffix(f"{self.path.suffix}.tmp")
            temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            temporary.replace(self.path)
            return row


class SuggestionApplication:
    def __init__(
        self,
        client: Any,
        suggestions_path: Path,
        feedback_path: Path,
        *,
        immich_public_url: str,
    ) -> None:
        self.client = client
        self.suggestions_path = suggestions_path
        self.feedback = FeedbackStore(feedback_path)
        self.immich_public_url = immich_public_url.rstrip("/")

    def suggestions(self) -> dict[str, Any]:
        value = json.loads(self.suggestions_path.read_text(encoding="utf-8"))
        rows = value.get("memories") if isinstance(value, dict) else None
        if not isinstance(rows, list):
            raise ValueError("Suggestion JSON does not contain memories")
        feedback = self.feedback.read()["events"]
        output = []
        for memory in rows:
            if not isinstance(memory, dict) or not isinstance(memory.get("event_id"), str):
                continue
            row = dict(memory)
            row["feedback"] = feedback.get(memory["event_id"], {"status": "pending"})
            output.append(row)
        return {"counts": value.get("counts", {}), "memories": output}

    def memory(self, event_id: str) -> dict[str, Any]:
        matches = [row for row in self.suggestions()["memories"] if row.get("event_id") == event_id]
        if len(matches) != 1:
            raise ValueError("Suggestion was not found exactly once")
        return matches[0]

    def hold(self, event_id: str) -> dict[str, Any]:
        self.memory(event_id)
        return self.feedback.set_status(event_id, "held")

    def create_review(self, event_id: str) -> dict[str, Any]:
        memory = self.memory(event_id)
        start = str(memory.get("start", ""))[:10] or "Undated"
        document = {"memories": [memory]}
        live_ids = {
            identifier
            for asset in self.client.iter_timeline_assets()
            if isinstance((identifier := asset.get("id")), str) and identifier
        }
        result = create_review_album(
            self.client,
            document,
            name=f"Curator Suggestion - {start}",
            event_limit=1,
            max_assets=20,
            apply=True,
            live_timeline_ids=live_ids,
        )
        album_id = result.get("album_id")
        if not isinstance(album_id, str):
            raise ValueError("Review Album response has no id")
        self.feedback.set_status(event_id, "review_album_created", album_id)
        return {
            **result,
            "immich_url": f"{self.immich_public_url}/albums/{album_id}" if self.immich_public_url else None,
        }


def _handler(
    app: SuggestionApplication, username: str | None, password: str | None
) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        server_version = "ImmichCurator/0.3"

        def _authorized(self) -> bool:
            if username is None or password is None:
                return True
            raw = self.headers.get("Authorization", "")
            if not raw.startswith("Basic "):
                return False
            try:
                supplied = base64.b64decode(raw[6:]).decode("utf-8")
            except Exception:
                return False
            return hmac.compare_digest(supplied, f"{username}:{password}")

        def _authenticate(self) -> bool:
            if self._authorized():
                return True
            self.send_response(HTTPStatus.UNAUTHORIZED)
            self.send_header("WWW-Authenticate", 'Basic realm="Curator Suggestions", charset="UTF-8"')
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            return False

        def _json(self, status: int, value: object) -> None:
            payload = json.dumps(value, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(payload)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(payload)

        def _error(self, status: int, message: str) -> None:
            self._json(status, {"error": message})

        def do_GET(self) -> None:
            if not self._authenticate():
                return
            path = urlparse(self.path).path
            try:
                if path == "/api/suggestions":
                    self._json(HTTPStatus.OK, app.suggestions())
                    return
                if path.startswith("/api/thumbnail/"):
                    identifier = unquote(path.removeprefix("/api/thumbnail/"))
                    if not identifier or "/" in identifier:
                        self._error(HTTPStatus.BAD_REQUEST, "Invalid Asset ID")
                        return
                    payload = app.client.thumbnail(identifier)
                    self.send_response(HTTPStatus.OK)
                    self.send_header("Content-Type", "image/jpeg")
                    self.send_header("Content-Length", str(len(payload)))
                    self.send_header("Cache-Control", "private, max-age=300")
                    self.end_headers()
                    self.wfile.write(payload)
                    return
                if path in {"/", "/index.html"}:
                    payload = files("curator.web").joinpath("index.html").read_bytes()
                    self.send_response(HTTPStatus.OK)
                    self.send_header("Content-Type", "text/html; charset=utf-8")
                    self.send_header("Content-Length", str(len(payload)))
                    self.send_header("Cache-Control", "no-cache")
                    self.end_headers()
                    self.wfile.write(payload)
                    return
                self._error(HTTPStatus.NOT_FOUND, "Not found")
            except (OSError, RuntimeError, ValueError, json.JSONDecodeError) as exc:
                self._error(HTTPStatus.INTERNAL_SERVER_ERROR, str(exc))

        def do_POST(self) -> None:
            if not self._authenticate():
                return
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if length < 1 or length > 16_384:
                    self._error(HTTPStatus.BAD_REQUEST, "Invalid request size")
                    return
                body = json.loads(self.rfile.read(length))
                event_id = body.get("event_id") if isinstance(body, dict) else None
                if not isinstance(event_id, str) or not event_id:
                    self._error(HTTPStatus.BAD_REQUEST, "event_id is required")
                    return
                if self.path == "/api/hold":
                    self._json(HTTPStatus.OK, app.hold(event_id))
                    return
                if self.path == "/api/review":
                    self._json(HTTPStatus.OK, app.create_review(event_id))
                    return
                self._error(HTTPStatus.NOT_FOUND, "Not found")
            except (OSError, RuntimeError, ValueError, json.JSONDecodeError) as exc:
                self._error(HTTPStatus.BAD_REQUEST, str(exc))

        def log_message(self, format: str, *args: object) -> None:
            print(f"suggestions-app: {self.address_string()} {format % args}")

    return Handler


def serve_suggestions(
    app: SuggestionApplication,
    *,
    host: str,
    port: int,
    username: str | None,
    password: str | None,
) -> None:
    if host not in {"127.0.0.1", "::1", "localhost"} and (not username or not password):
        raise ValueError("Basic authentication is required for non-loopback binding")
    server = ThreadingHTTPServer((host, port), _handler(app, username, password))
    print(json.dumps({"status": "listening", "url": f"http://{host}:{port}"}, ensure_ascii=False), flush=True)
    server.serve_forever()
