from __future__ import annotations

from datetime import datetime, timezone
from pathlib import PurePosixPath
from typing import Any, Iterable


PREFIXES = ("/photoprism/originals/", "/data/")


def normalize_path(value: str) -> str:
    path = value.strip().replace("\\", "/")
    for prefix in PREFIXES:
        if path.startswith(prefix):
            path = path[len(prefix) :]
            break
    path = path.lstrip("/")
    normalized = PurePosixPath(path).as_posix()
    if normalized in {"", "."} or normalized.startswith("../") or normalized == "..":
        raise ValueError(f"Unsafe or empty media path: {value!r}")
    return normalized


def immich_path(asset: dict[str, Any]) -> str | None:
    value = asset.get("originalPath")
    return normalize_path(value) if isinstance(value, str) and value.strip() else None


def photoprism_path(photo: dict[str, Any]) -> str | None:
    path = photo.get("Path")
    name = photo.get("Name") or photo.get("FileName")
    if isinstance(path, str) and path.strip():
        if isinstance(name, str) and name.strip() and PurePosixPath(path).name != name:
            return normalize_path(f"{path.rstrip('/')}/{name}")
        return normalize_path(path)
    files = photo.get("Files")
    if isinstance(files, list):
        for file in files:
            if not isinstance(file, dict):
                continue
            file_name = file.get("Name") or file.get("FileName")
            file_path = file.get("Path")
            if isinstance(file_path, str) and file_path.strip():
                if isinstance(file_name, str) and file_name.strip() and PurePosixPath(file_path).name != file_name:
                    return normalize_path(f"{file_path.rstrip('/')}/{file_name}")
                return normalize_path(file_path)
    return None


def _pick(source: dict[str, Any], names: tuple[str, ...]) -> Any:
    for name in names:
        if name in source:
            return source[name]
    return None


def reconcile(
    immich_assets: Iterable[dict[str, Any]], photoprism_photos: Iterable[dict[str, Any]]
) -> dict[str, Any]:
    immich_by_path: dict[str, dict[str, Any]] = {}
    for asset in immich_assets:
        path = immich_path(asset)
        if path:
            immich_by_path[path] = asset

    photo_by_path: dict[str, dict[str, Any]] = {}
    duplicate_photo_paths: set[str] = set()
    for photo in photoprism_photos:
        path = photoprism_path(photo)
        if not path:
            continue
        if path in photo_by_path:
            duplicate_photo_paths.add(path)
        else:
            photo_by_path[path] = photo

    candidates: list[dict[str, Any]] = []
    for path in sorted(immich_by_path.keys() & photo_by_path.keys()):
        asset = immich_by_path[path]
        photo = photo_by_path[path]
        exif = asset.get("exifInfo") if isinstance(asset.get("exifInfo"), dict) else {}
        candidates.append(
            {
                "relative_path": path,
                "immich": {
                    "id": asset.get("id"),
                    "type": asset.get("type"),
                    "file_created_at": asset.get("fileCreatedAt"),
                    "local_date_time": asset.get("localDateTime"),
                    "favorite": bool(asset.get("isFavorite", False)),
                    "width": exif.get("exifImageWidth"),
                    "height": exif.get("exifImageHeight"),
                    "latitude": exif.get("latitude"),
                    "longitude": exif.get("longitude"),
                },
                "photoprism": {
                    "uid": _pick(photo, ("UID", "PhotoUID")),
                    "id": photo.get("ID"),
                    "taken_at": photo.get("TakenAt"),
                    "type": photo.get("Type"),
                    "camera": _pick(photo, ("Camera", "CameraModel")),
                    "lens": photo.get("Lens"),
                    "quality": photo.get("Quality"),
                    "color": photo.get("Color"),
                    "latitude": photo.get("Lat"),
                    "longitude": photo.get("Lng"),
                    "labels": photo.get("Labels") if isinstance(photo.get("Labels"), list) else [],
                },
            }
        )

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "counts": {
            "immich_timeline": len(immich_by_path),
            "photoprism_indexed": len(photo_by_path),
            "matched": len(candidates),
            "immich_unmatched": len(immich_by_path.keys() - photo_by_path.keys()),
            "photoprism_unmatched": len(photo_by_path.keys() - immich_by_path.keys()),
            "photoprism_duplicate_paths": len(duplicate_photo_paths),
        },
        "candidates": candidates,
    }
