from __future__ import annotations

import hashlib
import math
from collections import Counter
from datetime import datetime, time, timedelta, timezone
from typing import Any, Iterable, Protocol

from .memories import asset_datetime


class TripAlbumClient(Protocol):
    def find_owned_albums(self, name: str) -> list[dict[str, Any]]: ...
    def create_album(self, name: str, description: str) -> dict[str, Any]: ...
    def add_assets_to_album(self, album_id: str, asset_ids: list[str]) -> None: ...
    def iter_album_assets(self, album_id: str): ...


def _coordinates(asset: dict[str, Any]) -> tuple[float, float] | None:
    exif = asset.get("exifInfo")
    if not isinstance(exif, dict):
        return None
    latitude = exif.get("latitude")
    longitude = exif.get("longitude")
    if not isinstance(latitude, (int, float)) or not isinstance(longitude, (int, float)):
        return None
    if not (-90 <= latitude <= 90 and -180 <= longitude <= 180):
        return None
    return float(latitude), float(longitude)


def distance_km(left: tuple[float, float], right: tuple[float, float]) -> float:
    radius = 6371.0088
    lat1, lon1 = map(math.radians, left)
    lat2, lon2 = map(math.radians, right)
    delta_lat = lat2 - lat1
    delta_lon = lon2 - lon1
    value = (
        math.sin(delta_lat / 2) ** 2
        + math.cos(lat1) * math.cos(lat2) * math.sin(delta_lon / 2) ** 2
    )
    return radius * 2 * math.atan2(math.sqrt(value), math.sqrt(max(1 - value, 0)))


def infer_home(assets: Iterable[dict[str, Any]]) -> tuple[float, float] | None:
    cells = Counter(
        (round(latitude, 1), round(longitude, 1))
        for asset in assets
        if (coordinates := _coordinates(asset)) is not None
        for latitude, longitude in [coordinates]
    )
    return cells.most_common(1)[0][0] if cells else None


def _location_label(anchors: list[dict[str, Any]]) -> str:
    labels: list[str] = []
    for asset in anchors:
        exif = asset.get("exifInfo")
        if not isinstance(exif, dict):
            continue
        parts = [exif.get("city"), exif.get("state"), exif.get("country")]
        label = ", ".join(str(part).strip() for part in parts if part)
        if label:
            labels.append(label)
    if labels:
        return Counter(labels).most_common(1)[0][0]
    coordinates = [_coordinates(asset) for asset in anchors]
    valid = [item for item in coordinates if item is not None]
    if not valid:
        return "Unknown location"
    latitude = sum(item[0] for item in valid) / len(valid)
    longitude = sum(item[1] for item in valid) / len(valid)
    return f"{latitude:.3f}, {longitude:.3f}"


def build_trip_candidates(
    assets: Iterable[dict[str, Any]],
    *,
    home: tuple[float, float] | None = None,
    away_km: float = 50.0,
    anchor_gap_hours: float = 36.0,
    minimum_anchors: int = 3,
    minimum_assets: int = 10,
) -> dict[str, Any]:
    source = [asset for asset in assets if asset_datetime(asset) is not None]
    resolved_home = home or infer_home(source)
    if resolved_home is None:
        raise ValueError("Cannot detect trips because no GPS coordinates were found")
    anchors = [
        asset
        for asset in source
        if (coordinates := _coordinates(asset)) is not None
        and distance_km(resolved_home, coordinates) >= away_km
    ]
    anchors.sort(key=lambda asset: asset_datetime(asset) or datetime.min.replace(tzinfo=timezone.utc))
    groups: list[list[dict[str, Any]]] = []
    for anchor in anchors:
        taken = asset_datetime(anchor)
        previous = asset_datetime(groups[-1][-1]) if groups else None
        if previous is None or taken is None or taken - previous > timedelta(hours=anchor_gap_hours):
            groups.append([])
        groups[-1].append(anchor)

    candidates: list[dict[str, Any]] = []
    for group in groups:
        if len(group) < minimum_anchors:
            continue
        first = asset_datetime(group[0])
        last = asset_datetime(group[-1])
        if first is None or last is None:
            continue
        start = datetime.combine(first.date(), time.min, tzinfo=first.tzinfo)
        end = datetime.combine(last.date(), time.max, tzinfo=last.tzinfo)
        trip_assets = [
            asset
            for asset in source
            if (taken := asset_datetime(asset)) is not None and start <= taken <= end
        ]
        if len(trip_assets) < minimum_assets:
            continue
        anchor_times = [asset_datetime(asset) for asset in group]
        rows: list[dict[str, Any]] = []
        for asset in sorted(trip_assets, key=lambda item: asset_datetime(item) or start):
            taken = asset_datetime(asset)
            has_gps = _coordinates(asset) is not None
            nearest_seconds = min(
                abs((taken - anchor_time).total_seconds())
                for anchor_time in anchor_times
                if taken is not None and anchor_time is not None
            )
            confidence = "exact" if has_gps else "high" if nearest_seconds <= 1800 else "medium" if nearest_seconds <= 21600 else "low"
            rows.append(
                {
                    "id": asset.get("id"),
                    "taken_at": taken.isoformat() if taken else None,
                    "has_gps": has_gps,
                    "inference_confidence": confidence,
                    "nearest_gps_minutes": 0 if has_gps else round(nearest_seconds / 60, 1),
                    "original_path": asset.get("originalPath"),
                }
            )
        label = _location_label(group)
        seed = f"{start.date()}:{end.date()}:{label}"
        candidates.append(
            {
                "trip_id": hashlib.sha256(seed.encode()).hexdigest()[:12],
                "label": label,
                "start": start.isoformat(),
                "end": end.isoformat(),
                "anchor_count": len(group),
                "asset_count": len(rows),
                "gps_asset_count": sum(row["has_gps"] for row in rows),
                "inferred_asset_count": sum(not row["has_gps"] for row in rows),
                "suggested_album_name": f"Trip Candidate - {label} - {start.date()}",
                "assets": rows,
            }
        )
    candidates.sort(key=lambda item: item["start"], reverse=True)
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "policy": {
            "source": "immich_live_timeline_with_exif",
            "home": {"latitude": resolved_home[0], "longitude": resolved_home[1], "inferred": home is None},
            "away_km": away_km,
            "anchor_gap_hours": anchor_gap_hours,
            "minimum_anchors": minimum_anchors,
            "minimum_assets": minimum_assets,
            "writes_to_immich": False,
            "writes_location_metadata": False,
        },
        "counts": {
            "timeline_assets": len(source),
            "gps_assets": sum(_coordinates(asset) is not None for asset in source),
            "away_gps_anchors": len(anchors),
            "trip_candidates": len(candidates),
        },
        "trips": candidates,
    }


def create_trip_candidate_album(
    client: TripAlbumClient | None,
    trip_data: dict[str, Any],
    *,
    trip_id: str,
    apply: bool = False,
    live_timeline_ids: set[str] | None = None,
) -> dict[str, Any]:
    trips = trip_data.get("trips")
    if not isinstance(trips, list):
        raise ValueError("Trip JSON does not contain a trips list")
    matches = [trip for trip in trips if isinstance(trip, dict) and trip.get("trip_id") == trip_id]
    if len(matches) != 1:
        raise ValueError(f"Trip ID {trip_id!r} was not found exactly once")
    trip = matches[0]
    name = trip.get("suggested_album_name")
    if not isinstance(name, str) or not name.strip():
        raise ValueError("Trip candidate has no album name")
    rows = trip.get("assets")
    if not isinstance(rows, list):
        raise ValueError("Trip candidate has no assets list")
    requested = [row.get("id") for row in rows if isinstance(row, dict) and isinstance(row.get("id"), str)]
    if apply and live_timeline_ids is None:
        raise ValueError("Live Timeline IDs are required before applying a trip album")
    asset_ids = [identifier for identifier in requested if live_timeline_ids is None or identifier in live_timeline_ids]
    plan = {
        "mode": "apply" if apply else "dry-run",
        "trip_id": trip_id,
        "album_name": name,
        "asset_count": len(asset_ids),
        "excluded_not_timeline": len(requested) - len(asset_ids),
        "asset_ids": asset_ids,
    }
    if not apply:
        return plan
    if client is None or not asset_ids:
        raise ValueError("Refusing to create an empty trip album")
    if client.find_owned_albums(name):
        raise ValueError("Trip candidate album already exists; immutable albums are never updated")
    album = client.create_album(
        name,
        "Generated once by Immich Curator. Photo metadata and visibility are unchanged; this album is not automatically updated.",
    )
    album_id = album.get("id")
    if not isinstance(album_id, str) or not album_id:
        raise ValueError("Album response has no id")
    client.add_assets_to_album(album_id, asset_ids)
    present = {asset.get("id") for asset in client.iter_album_assets(album_id) if isinstance(asset, dict)}
    missing = [identifier for identifier in asset_ids if identifier not in present]
    if missing:
        raise ValueError(f"Trip album verification failed: {len(missing)} assets missing")
    return {**plan, "album_id": album_id, "verified": True, "immutable_by_convention": True}
