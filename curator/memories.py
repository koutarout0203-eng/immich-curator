from __future__ import annotations

import hashlib
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable


def asset_datetime(asset: dict[str, Any]) -> datetime | None:
    for field in ("localDateTime", "fileCreatedAt", "fileModifiedAt"):
        value = asset.get(field)
        if not isinstance(value, str) or not value.strip():
            continue
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            continue
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    return None


def group_events(
    assets: Iterable[dict[str, Any]], *, gap: timedelta = timedelta(hours=6)
) -> list[list[dict[str, Any]]]:
    dated = [(taken, asset) for asset in assets if (taken := asset_datetime(asset)) is not None]
    dated.sort(key=lambda item: item[0])
    events: list[list[dict[str, Any]]] = []
    previous: datetime | None = None
    for taken, asset in dated:
        if previous is None or taken - previous > gap:
            events.append([])
        events[-1].append(asset)
        previous = taken
    return events


def select_representatives(assets: list[dict[str, Any]], limit: int) -> list[dict[str, Any]]:
    if len(assets) <= limit:
        return list(assets)
    selected: list[dict[str, Any]] = [asset for asset in assets if asset.get("isFavorite") is True][
        :limit
    ]
    selected_ids = {asset.get("id") for asset in selected}
    remaining_slots = limit - len(selected)
    if remaining_slots <= 0:
        return selected

    remaining = [asset for asset in assets if asset.get("id") not in selected_ids]
    for slot in range(remaining_slots):
        index = round(slot * (len(remaining) - 1) / max(remaining_slots - 1, 1))
        asset = remaining[index]
        if asset.get("id") not in selected_ids:
            selected.append(asset)
            selected_ids.add(asset.get("id"))
    return sorted(selected, key=lambda asset: asset_datetime(asset) or datetime.min.replace(tzinfo=timezone.utc))


def _location(asset: dict[str, Any]) -> dict[str, Any] | None:
    exif = asset.get("exifInfo")
    if not isinstance(exif, dict):
        return None
    fields = {
        "city": exif.get("city"),
        "state": exif.get("state"),
        "country": exif.get("country"),
        "latitude": exif.get("latitude"),
        "longitude": exif.get("longitude"),
    }
    return fields if any(value is not None for value in fields.values()) else None


def build_memories(
    assets: Iterable[dict[str, Any]],
    *,
    gap_hours: int = 6,
    min_assets: int = 3,
    max_assets: int = 12,
    max_memories: int = 50,
) -> dict[str, Any]:
    source = list(assets)
    events = group_events(source, gap=timedelta(hours=gap_hours))
    memories: list[dict[str, Any]] = []
    for event in events:
        if len(event) < min_assets:
            continue
        start = asset_datetime(event[0])
        end = asset_datetime(event[-1])
        if start is None or end is None:
            continue
        representatives = select_representatives(event, max_assets)
        favorite_count = sum(asset.get("isFavorite") is True for asset in event)
        locations = [location for asset in event if (location := _location(asset))]
        seed = str(event[0].get("id") or event[0].get("originalPath") or start.isoformat())
        memories.append(
            {
                "event_id": f"{start.date()}-{hashlib.sha256(seed.encode()).hexdigest()[:8]}",
                "start": start.isoformat(),
                "end": end.isoformat(),
                "asset_count": len(event),
                "favorite_count": favorite_count,
                "location": locations[0] if locations else None,
                "suggestion_score": favorite_count * 10 + min(len(event), 20) + (3 if locations else 0),
                "assets": [
                    {
                        "id": asset.get("id"),
                        "type": asset.get("type"),
                        "taken_at": (asset_datetime(asset) or start).isoformat(),
                        "favorite": bool(asset.get("isFavorite", False)),
                        "original_path": asset.get("originalPath"),
                    }
                    for asset in representatives
                ],
            }
        )
    memories.sort(key=lambda memory: (memory["suggestion_score"], memory["start"]), reverse=True)
    eligible_memories = len(memories)
    memories = memories[:max_memories]
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "policy": {
            "source": "immich_timeline",
            "event_gap_hours": gap_hours,
            "minimum_event_assets": min_assets,
            "maximum_representatives": max_assets,
            "maximum_suggestions": max_memories,
            "writes_to_immich": False,
        },
        "counts": {
            "timeline_assets": len(source),
            "dated_assets": sum(asset_datetime(asset) is not None for asset in source),
            "events": len(events),
            "eligible_memories": eligible_memories,
            "memory_suggestions": len(memories),
        },
        "memories": memories,
    }
