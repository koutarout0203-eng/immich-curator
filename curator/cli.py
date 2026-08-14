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
    result = create_review_album(
        client,  # type: ignore[arg-type]
        memories,
        name=name,
        event_limit=event_limit,
        max_assets=max_assets,
        apply=apply,
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
