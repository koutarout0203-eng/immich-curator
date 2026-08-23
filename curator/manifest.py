from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


def formal_trip_name(trip: dict[str, Any]) -> str | None:
    name = trip.get("suggested_album_name")
    if not isinstance(name, str) or not name:
        return None
    return name.replace(" - Trip Candidate - ", " - Trip - ", 1)


def build_trip_manifest(
    client: Any,
    trip_data: dict[str, Any],
    *,
    immich_public_url: str = "",
) -> dict[str, Any]:
    rows = trip_data.get("trips")
    if not isinstance(rows, list):
        raise ValueError("Trip JSON does not contain a trips list")
    root = immich_public_url.rstrip("/")
    trips: list[dict[str, Any]] = []
    counts = {"trip_candidates": 0, "linked_albums": 0, "missing_albums": 0, "ambiguous_albums": 0}
    for trip in rows:
        if not isinstance(trip, dict):
            continue
        name = formal_trip_name(trip)
        trip_id = trip.get("trip_id")
        if not name or not isinstance(trip_id, str):
            continue
        counts["trip_candidates"] += 1
        matches = client.find_owned_albums(name)
        status = "linked" if len(matches) == 1 else "missing" if not matches else "ambiguous"
        counts[f"{status}_albums"] += 1
        album_id = matches[0].get("id") if len(matches) == 1 else None
        assets = trip.get("assets") if isinstance(trip.get("assets"), list) else []
        cover_id = next(
            (asset.get("id") for asset in assets if isinstance(asset, dict) and isinstance(asset.get("id"), str)),
            None,
        )
        trips.append({
            "trip_id": trip_id,
            "start": trip.get("start"),
            "end": trip.get("end"),
            "label": trip.get("label"),
            "asset_count": len(assets),
            "cover_asset_id": cover_id,
            "album": {
                "status": status,
                "id": album_id,
                "name": name,
                "url": f"{root}/albums/{album_id}" if root and isinstance(album_id, str) else None,
            },
        })
    trips.sort(key=lambda row: str(row.get("start") or ""), reverse=True)
    return {
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source": "immich-curator",
        "contains_secrets": False,
        "contains_photo_binaries": False,
        "counts": counts,
        "trips": trips,
    }
