from __future__ import annotations

import json
import os
import time
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterator
from zoneinfo import ZoneInfo

from .trips import (
    build_trip_candidates,
    create_all_trip_candidate_albums,
    normalize_home_periods,
)
from .manifest import build_trip_manifest
from .visual import build_visual_memories


def write_json_atomic(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(f"{path.suffix}.tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def mature_trip_data(
    trip_data: dict[str, Any], *, now: datetime, settle_hours: float
) -> dict[str, Any]:
    cutoff = now.astimezone(timezone.utc) - timedelta(hours=settle_hours)
    trips = trip_data.get("trips")
    if not isinstance(trips, list):
        raise ValueError("Trip data does not contain a trips list")
    mature: list[dict[str, Any]] = []
    pending: list[dict[str, Any]] = []
    for trip in trips:
        if not isinstance(trip, dict):
            continue
        raw = trip.get("last_away_anchor") or trip.get("end")
        try:
            ended = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
            if ended.tzinfo is None:
                ended = ended.replace(tzinfo=timezone.utc)
        except (TypeError, ValueError):
            pending.append(trip)
            continue
        (mature if ended.astimezone(timezone.utc) <= cutoff else pending).append(trip)
    result = dict(trip_data)
    result["trips"] = mature
    result["automation"] = {
        "settle_hours": settle_hours,
        "mature_trip_count": len(mature),
        "pending_trip_count": len(pending),
        "pending_trip_ids": [trip.get("trip_id") for trip in pending],
    }
    return result


def next_weekly_run(now: datetime, *, weekday: int, hour: int, minute: int) -> datetime:
    if weekday < 0 or weekday > 6:
        raise ValueError("weekday must be 0..6 where Monday is 0")
    candidate = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    candidate += timedelta(days=(weekday - candidate.weekday()) % 7)
    if candidate <= now:
        candidate += timedelta(days=7)
    return candidate


@contextmanager
def exclusive_run(lock_path: Path, *, stale_hours: float = 12) -> Iterator[None]:
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        descriptor = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        age = time.time() - lock_path.stat().st_mtime
        if age <= stale_hours * 3600:
            raise RuntimeError("A trip sync is already running")
        lock_path.unlink()
        descriptor = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    try:
        try:
            os.write(descriptor, f"pid={os.getpid()} started={datetime.now(timezone.utc).isoformat()}\n".encode())
        finally:
            os.close(descriptor)
        yield
    finally:
        lock_path.unlink(missing_ok=True)


def run_trip_sync(
    client: Any,
    *,
    home_periods_document: dict[str, Any],
    now: datetime,
    settle_hours: float = 72,
    page_size: int = 500,
    away_km: float = 50,
    anchor_gap_hours: float = 36,
    minimum_anchors: int = 3,
    minimum_assets: int = 10,
    trip_padding_hours: float = 3,
    historical_review_days: float = 30,
    immich_public_url: str = "",
    suggestion_event_limit: int = 10,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]]:
    assets = list(client.iter_timeline_assets(page_size=page_size))
    timeline_ids = {
        identifier
        for asset in assets
        if isinstance((identifier := asset.get("id")), str) and identifier
    }
    trips = build_trip_candidates(
        assets,
        home_periods=normalize_home_periods(home_periods_document),
        away_km=away_km,
        anchor_gap_hours=anchor_gap_hours,
        minimum_anchors=minimum_anchors,
        minimum_assets=minimum_assets,
        trip_padding_hours=trip_padding_hours,
    )
    mature = mature_trip_data(trips, now=now, settle_hours=settle_hours)
    automatic: list[dict[str, Any]] = []
    historical_review: list[dict[str, Any]] = []
    recent_cutoff = now.astimezone(timezone.utc) - timedelta(days=historical_review_days)
    for trip in mature["trips"]:
        suggested = trip.get("suggested_album_name")
        formal_name = (
            suggested.replace(" - Trip Candidate - ", " - Trip - ", 1)
            if isinstance(suggested, str)
            else None
        )
        raw_end = trip.get("last_away_anchor") or trip.get("end")
        try:
            ended = datetime.fromisoformat(str(raw_end).replace("Z", "+00:00"))
            if ended.tzinfo is None:
                ended = ended.replace(tzinfo=timezone.utc)
        except (TypeError, ValueError):
            historical_review.append(trip)
            continue
        existing = client.find_owned_albums(formal_name) if formal_name else []
        if existing or ended.astimezone(timezone.utc) >= recent_cutoff:
            automatic.append(trip)
        else:
            historical_review.append(trip)
    applicable = dict(mature)
    applicable["trips"] = automatic
    mature["automation"]["automatic_trip_count"] = len(automatic)
    mature["automation"]["historical_review_count"] = len(historical_review)
    mature["automation"]["historical_review_trip_ids"] = [trip.get("trip_id") for trip in historical_review]
    mature["automation"]["historical_review_days"] = historical_review_days
    result = create_all_trip_candidate_albums(
        client,
        applicable,
        apply=True,
        live_timeline_ids=timeline_ids,
        add_missing_to_conflicts=True,
    )
    result["automation"] = mature["automation"]
    manifest = build_trip_manifest(client, mature, immich_public_url=immich_public_url)
    suggestions = build_visual_memories(
        assets,
        client.thumbnail,
        event_limit=suggestion_event_limit,
        max_assets=8,
    )
    return mature, result, manifest, suggestions


def load_timezone(name: str) -> ZoneInfo:
    try:
        return ZoneInfo(name)
    except Exception as exc:
        raise ValueError(f"Unknown timezone: {name}") from exc
