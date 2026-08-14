from __future__ import annotations

import json
from collections.abc import Iterator
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.parse import quote
from urllib.request import Request, urlopen


class ApiError(RuntimeError):
    pass


class JsonClient:
    def __init__(self, timeout: float = 30.0) -> None:
        self.timeout = timeout

    def _json_request(
        self,
        method: str,
        url: str,
        headers: dict[str, str],
        body: dict[str, Any] | None = None,
    ) -> tuple[Any, dict[str, str]]:
        payload = json.dumps(body).encode("utf-8") if body is not None else None
        request = Request(url, data=payload, method=method, headers=headers)
        try:
            with urlopen(request, timeout=self.timeout) as response:
                raw = response.read()
                response_headers = {key.lower(): value for key, value in response.headers.items()}
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise ApiError(f"API HTTP {exc.code}: {detail[:500]}") from exc
        except URLError as exc:
            raise ApiError(f"API connection failed: {exc.reason}") from exc
        try:
            return (json.loads(raw) if raw else None), response_headers
        except json.JSONDecodeError as exc:
            raise ApiError("API returned invalid JSON") from exc


class ImmichClient(JsonClient):
    def __init__(self, base_url: str, api_key: str, timeout: float = 30.0) -> None:
        super().__init__(timeout)
        root = base_url.rstrip("/")
        self.api_root = root if root.endswith("/api") else f"{root}/api"
        self.headers = {
            "x-api-key": api_key,
            "Accept": "application/json",
            "Content-Type": "application/json",
        }

    def version(self) -> dict[str, Any]:
        result, _ = self._json_request("GET", f"{self.api_root}/server/version", self.headers)
        return result if isinstance(result, dict) else {}

    def iter_timeline_assets(self, page_size: int = 500) -> Iterator[dict[str, Any]]:
        page = 1
        while True:
            result, _ = self._json_request(
                "POST",
                f"{self.api_root}/search/metadata",
                self.headers,
                {"page": page, "size": page_size, "visibility": "timeline", "withExif": True},
            )
            assets = result.get("assets", {}) if isinstance(result, dict) else {}
            items = assets.get("items", []) if isinstance(assets, dict) else []
            if not isinstance(items, list):
                raise ApiError("Immich search response assets.items is not a list")
            for item in items:
                if not isinstance(item, dict):
                    continue
                if item.get("isArchived") is True or item.get("isTrashed") is True or item.get("deletedAt"):
                    continue
                yield item
            next_page = assets.get("nextPage")
            if next_page in (None, "", 0, "0"):
                break
            page = int(next_page)

    def find_owned_albums(self, name: str) -> list[dict[str, Any]]:
        result, _ = self._json_request(
            "GET", f"{self.api_root}/albums?name={quote(name)}&isOwned=true", self.headers
        )
        if not isinstance(result, list):
            raise ApiError("Immich album response is not a list")
        return [
            album
            for album in result
            if isinstance(album, dict) and album.get("albumName") == name
        ]

    def create_album(self, name: str, description: str) -> dict[str, Any]:
        result, _ = self._json_request(
            "POST",
            f"{self.api_root}/albums",
            self.headers,
            {"albumName": name, "description": description},
        )
        if not isinstance(result, dict) or not result.get("id"):
            raise ApiError("Unexpected Immich create album response")
        return result

    def add_assets_to_album(self, album_id: str, asset_ids: list[str]) -> None:
        result, _ = self._json_request(
            "PUT",
            f"{self.api_root}/albums/{album_id}/assets",
            self.headers,
            {"ids": asset_ids},
        )
        if not isinstance(result, list):
            raise ApiError("Unexpected Immich add assets response")

    def get_album(self, album_id: str) -> dict[str, Any]:
        result, _ = self._json_request(
            "GET", f"{self.api_root}/albums/{album_id}", self.headers
        )
        if not isinstance(result, dict) or result.get("id") != album_id:
            raise ApiError("Unexpected Immich album detail response")
        return result


class PhotoPrismClient(JsonClient):
    def __init__(self, base_url: str, token: str, timeout: float = 30.0) -> None:
        super().__init__(timeout)
        self.api_root = f"{base_url.rstrip('/')}/api/v1"
        self.headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}

    def iter_photos(self, page_size: int = 500) -> Iterator[dict[str, Any]]:
        offset = 0
        while True:
            query = urlencode({"count": page_size, "offset": offset, "merged": "true"})
            result, headers = self._json_request(
                "GET", f"{self.api_root}/photos?{query}", self.headers
            )
            if not isinstance(result, list):
                raise ApiError("PhotoPrism photos response is not a list")
            rows = [row for row in result if isinstance(row, dict)]
            yield from rows
            count = int(headers.get("x-count", len(rows)))
            limit = int(headers.get("x-limit", page_size))
            if count < limit or not rows:
                break
            offset += count
