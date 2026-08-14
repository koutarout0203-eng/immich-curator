from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from .clients import ApiError, ImmichClient, PhotoPrismClient
from .reconcile import reconcile


def _required(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise ValueError(f"{name} is required")
    return value


def _clients() -> tuple[ImmichClient, PhotoPrismClient]:
    timeout = float(os.environ.get("API_TIMEOUT_SECONDS", "30"))
    return (
        ImmichClient(_required("IMMICH_BASE_URL"), _required("IMMICH_API_KEY"), timeout),
        PhotoPrismClient(
            _required("PHOTOPRISM_BASE_URL"), _required("PHOTOPRISM_TOKEN"), timeout
        ),
    )


def _write_json_atomic(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(f"{path.suffix}.tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def run_probe() -> int:
    immich, photoprism = _clients()
    version = immich.version()
    first_photo = next(photoprism.iter_photos(page_size=1), None)
    print(json.dumps({"immich_version": version, "photoprism_api": "ok" if first_photo else "empty"}))
    return 0


def run_snapshot(output: str, page_size: int) -> int:
    immich, photoprism = _clients()
    result = reconcile(
        immich.iter_timeline_assets(page_size=page_size),
        photoprism.iter_photos(page_size=page_size),
    )
    output_path = Path(output)
    _write_json_atomic(output_path, result)
    print(json.dumps({"output": str(output_path), "counts": result["counts"]}, ensure_ascii=False))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="immich-curator")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("probe", help="verify read-only API access")
    snapshot = subparsers.add_parser("snapshot", help="write matched metadata snapshot")
    snapshot.add_argument("--output", default="/data/candidates.json")
    snapshot.add_argument("--page-size", type=int, default=500)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "probe":
            return run_probe()
        if args.page_size < 1 or args.page_size > 1000:
            raise ValueError("--page-size must be between 1 and 1000")
        return run_snapshot(args.output, args.page_size)
    except (ApiError, OSError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
