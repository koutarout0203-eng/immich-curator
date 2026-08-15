from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from .clients import ApiError, ImmichClient, PhotoPrismClient
from .memories import build_memories
from .reconcile import reconcile
from .review import create_review_album
from .trips import build_trip_candidates, create_trip_candidate_album
from .visual import build_visual_memories


def _required(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise ValueError(f"{name} is required")
    return value


def _immich_client() -> ImmichClient:
    timeout = float(os.environ.get("API_TIMEOUT_SECONDS", "30"))
    return ImmichClient(_required("IMMICH_BASE_URL"), _required("IMMICH_API_KEY"), timeout)


def _photoprism_client() -> PhotoPrismClient:
    return PhotoPrismClient(
        _required("PHOTOPRISM_BASE_URL"),
        _required("PHOTOPRISM_TOKEN"),
        float(os.environ.get("API_TIMEOUT_SECONDS", "30")),
    )


def _write_json_atomic(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(f"{path.suffix}.tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def run_probe() -> int:
    immich = _immich_client()
    version = immich.version()
    print(json.dumps({"immich_version": version, "immich_api": "ok"}))
    return 0


def run_snapshot(output: str, page_size: int) -> int:
    immich = _immich_client()
    photoprism = _photoprism_client()
    result = reconcile(
        immich.iter_timeline_assets(page_size=page_size),
        photoprism.iter_photos(page_size=page_size),
    )
    output_path = Path(output)
    _write_json_atomic(output_path, result)
    print(json.dumps({"output": str(output_path), "counts": result["counts"]}, ensure_ascii=False))
    return 0


def run_memories(
    output: str,
    page_size: int,
    gap_hours: int,
    min_assets: int,
    max_assets: int,
    max_memories: int,
) -> int:
    immich = _immich_client()
    result = build_memories(
        immich.iter_timeline_assets(page_size=page_size),
        gap_hours=gap_hours,
        min_assets=min_assets,
        max_assets=max_assets,
        max_memories=max_memories,
    )
    output_path = Path(output)
    _write_json_atomic(output_path, result)
    print(json.dumps({"output": str(output_path), "counts": result["counts"]}, ensure_ascii=False))
    return 0


def run_review_album(
    input_path: str, name: str, event_limit: int, max_assets: int, apply: bool
) -> int:
    memories = json.loads(Path(input_path).read_text(encoding="utf-8"))
    if not isinstance(memories, dict):
        raise ValueError("Memory JSON root must be an object")
    client = _immich_client() if apply else None
    live_timeline_ids = (
        {
            identifier
            for asset in client.iter_timeline_assets()
            if isinstance((identifier := asset.get("id")), str) and identifier
        }
        if client is not None
        else None
    )
    result = create_review_album(
        client,  # type: ignore[arg-type]
        memories,
        name=name,
        event_limit=event_limit,
        max_assets=max_assets,
        apply=apply,
        live_timeline_ids=live_timeline_ids,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def run_visual_memories(
    output: str,
    event_limit: int,
    max_assets: int,
    similarity_distance: int,
    phash_distance: int,
    sequence_seconds: int,
    burst_seconds: int,
) -> int:
    client = _immich_client()
    assets = list(client.iter_timeline_assets())
    result = build_visual_memories(
        assets,
        client.thumbnail,
        event_limit=event_limit,
        max_assets=max_assets,
        similarity_distance=similarity_distance,
        phash_distance=phash_distance,
        sequence_seconds=sequence_seconds,
        burst_seconds=burst_seconds,
    )
    output_path = Path(output)
    _write_json_atomic(output_path, result)
    print(json.dumps({"output": str(output_path), "counts": result["counts"]}, ensure_ascii=False))
    return 0


def run_trip_candidates(
    output: str,
    page_size: int,
    home_lat: float | None,
    home_lon: float | None,
    away_km: float,
    anchor_gap_hours: float,
    minimum_anchors: int,
    minimum_assets: int,
) -> int:
    client = _immich_client()
    home = (home_lat, home_lon) if home_lat is not None and home_lon is not None else None
    result = build_trip_candidates(
        client.iter_timeline_assets(page_size=page_size),
        home=home,
        away_km=away_km,
        anchor_gap_hours=anchor_gap_hours,
        minimum_anchors=minimum_anchors,
        minimum_assets=minimum_assets,
    )
    output_path = Path(output)
    _write_json_atomic(output_path, result)
    print(json.dumps({"output": str(output_path), "counts": result["counts"], "home": result["policy"]["home"]}, ensure_ascii=False))
    return 0


def run_trip_album(input_path: str, trip_id: str, apply: bool) -> int:
    trip_data = json.loads(Path(input_path).read_text(encoding="utf-8"))
    if not isinstance(trip_data, dict):
        raise ValueError("Trip JSON root must be an object")
    client = _immich_client() if apply else None
    live_timeline_ids = (
        {
            identifier
            for asset in client.iter_timeline_assets()
            if isinstance((identifier := asset.get("id")), str) and identifier
        }
        if client is not None
        else None
    )
    result = create_trip_candidate_album(
        client,
        trip_data,
        trip_id=trip_id,
        apply=apply,
        live_timeline_ids=live_timeline_ids,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="immich-curator")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("probe", help="verify read-only API access")
    memories = subparsers.add_parser("memories", help="build Immich-only memory suggestions")
    memories.add_argument("--output", default="/data/memories.json")
    memories.add_argument("--page-size", type=int, default=500)
    memories.add_argument("--gap-hours", type=int, default=6)
    memories.add_argument("--min-assets", type=int, default=3)
    memories.add_argument("--max-assets", type=int, default=12)
    memories.add_argument("--max-memories", type=int, default=50)
    snapshot = subparsers.add_parser(
        "snapshot", help="optional PhotoPrism metadata reconciliation"
    )
    snapshot.add_argument("--output", default="/data/candidates.json")
    snapshot.add_argument("--page-size", type=int, default=500)
    review = subparsers.add_parser("review-album", help="plan or create an Immich review album")
    review.add_argument("--input", default="/data/memories.json")
    review.add_argument("--name", default="Curator Memory Review")
    review.add_argument("--events", type=int, default=5)
    review.add_argument("--max-assets", type=int, default=60)
    review.add_argument("--apply", action="store_true")
    visual = subparsers.add_parser(
        "visual-memories", help="rank live Immich events using preview thumbnails"
    )
    visual.add_argument("--output", default="/data/visual-memories.json")
    visual.add_argument("--events", type=int, default=5)
    visual.add_argument("--max-assets", type=int, default=8)
    visual.add_argument("--similarity-distance", type=int, default=8)
    visual.add_argument("--phash-distance", type=int, default=12)
    visual.add_argument("--sequence-seconds", type=int, default=120)
    visual.add_argument("--burst-seconds", type=int, default=15)
    trips = subparsers.add_parser(
        "trip-candidates", help="detect immutable trip album candidates from GPS anchors"
    )
    trips.add_argument("--output", default="/data/trips.json")
    trips.add_argument("--page-size", type=int, default=500)
    trips.add_argument("--home-lat", type=float)
    trips.add_argument("--home-lon", type=float)
    trips.add_argument("--away-km", type=float, default=50.0)
    trips.add_argument("--anchor-gap-hours", type=float, default=36.0)
    trips.add_argument("--minimum-anchors", type=int, default=3)
    trips.add_argument("--minimum-assets", type=int, default=10)
    trip_album = subparsers.add_parser(
        "trip-album", help="plan or create one immutable trip candidate album"
    )
    trip_album.add_argument("--input", default="/data/trips.json")
    trip_album.add_argument("--trip-id", required=True)
    trip_album.add_argument("--apply", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "probe":
            return run_probe()
        if args.command == "review-album":
            if args.events < 1 or args.max_assets < 1 or args.max_assets > 100:
                raise ValueError("review limits must be positive and --max-assets must not exceed 100")
            return run_review_album(
                args.input, args.name.strip(), args.events, args.max_assets, args.apply
            )
        if args.command == "visual-memories":
            if (
                args.events < 1
                or args.events > 20
                or args.max_assets < 1
                or args.max_assets > 20
                or args.similarity_distance < 0
                or args.similarity_distance > 24
                or args.phash_distance < 0
                or args.phash_distance > 24
                or args.sequence_seconds < 0
                or args.sequence_seconds > 3600
                or args.burst_seconds < 0
                or args.burst_seconds > 300
            ):
                raise ValueError("visual policy values are outside their safe limits")
            return run_visual_memories(
                args.output,
                args.events,
                args.max_assets,
                args.similarity_distance,
                args.phash_distance,
                args.sequence_seconds,
                args.burst_seconds,
            )
        if args.command == "trip-album":
            return run_trip_album(args.input, args.trip_id.strip(), args.apply)
        if args.command == "trip-candidates":
            if (args.home_lat is None) != (args.home_lon is None):
                raise ValueError("--home-lat and --home-lon must be provided together")
            if (
                args.page_size < 1
                or args.page_size > 1000
                or args.away_km <= 0
                or args.anchor_gap_hours <= 0
                or args.minimum_anchors < 1
                or args.minimum_assets < 1
            ):
                raise ValueError("trip policy values must be positive and page size must be 1..1000")
            return run_trip_candidates(
                args.output,
                args.page_size,
                args.home_lat,
                args.home_lon,
                args.away_km,
                args.anchor_gap_hours,
                args.minimum_anchors,
                args.minimum_assets,
            )
        if args.page_size < 1 or args.page_size > 1000:
            raise ValueError("--page-size must be between 1 and 1000")
        if args.command == "memories":
            if (
                args.gap_hours < 1
                or args.min_assets < 1
                or args.max_assets < 1
                or args.max_memories < 1
            ):
                raise ValueError("memory policy values must be positive")
            return run_memories(
                args.output,
                args.page_size,
                args.gap_hours,
                args.min_assets,
                args.max_assets,
                args.max_memories,
            )
        return run_snapshot(args.output, args.page_size)
    except (ApiError, OSError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
