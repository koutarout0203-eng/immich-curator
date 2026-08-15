from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from io import BytesIO
from typing import Any, Callable

from PIL import Image, ImageFilter, ImageOps, ImageStat, UnidentifiedImageError

from .memories import asset_datetime, group_events


@dataclass(frozen=True)
class ImageMetrics:
    dhash: int
    phash: int
    sharpness: float
    brightness: float
    dark_fraction: float
    bright_fraction: float
    technical_score: float

    def json(self) -> dict[str, Any]:
        value = asdict(self)
        value["dhash"] = f"{self.dhash:016x}"
        value["phash"] = f"{self.phash:016x}"
        return value


def _phash(gray: Image.Image) -> int:
    size = 32
    low = 8
    pixels = list(gray.resize((size, size), Image.Resampling.LANCZOS).get_flattened_data())
    cosines = [
        [math.cos((2 * position + 1) * frequency * math.pi / (2 * size)) for position in range(size)]
        for frequency in range(low)
    ]
    coefficients: list[float] = []
    for vertical in range(low):
        for horizontal in range(low):
            value = 0.0
            for y in range(size):
                row_factor = cosines[vertical][y]
                offset = y * size
                for x in range(size):
                    value += pixels[offset + x] * row_factor * cosines[horizontal][x]
            coefficients.append(value)
    median_source = sorted(coefficients[1:])
    median = median_source[len(median_source) // 2]
    result = 0
    for coefficient in coefficients:
        result = (result << 1) | int(coefficient > median)
    return result


def analyze_image(raw: bytes) -> ImageMetrics:
    try:
        with Image.open(BytesIO(raw)) as opened:
            image = ImageOps.exif_transpose(opened).convert("RGB")
    except (UnidentifiedImageError, OSError) as exc:
        raise ValueError("Thumbnail is not a supported image") from exc
    image.thumbnail((512, 512), Image.Resampling.LANCZOS)
    gray = ImageOps.grayscale(image)
    hash_image = gray.resize((9, 8), Image.Resampling.LANCZOS)
    pixels = list(hash_image.get_flattened_data())
    dhash = 0
    for row in range(8):
        for column in range(8):
            dhash = (dhash << 1) | int(
                pixels[row * 9 + column] > pixels[row * 9 + column + 1]
            )

    edges = gray.filter(ImageFilter.FIND_EDGES)
    if edges.width > 4 and edges.height > 4:
        edges = edges.crop((2, 2, edges.width - 2, edges.height - 2))
    sharpness = float(ImageStat.Stat(edges).var[0])
    histogram = gray.histogram()
    total = max(sum(histogram), 1)
    brightness = sum(level * count for level, count in enumerate(histogram)) / total
    dark_fraction = sum(histogram[:16]) / total
    bright_fraction = sum(histogram[240:]) / total
    exposure_penalty = abs(brightness - 128.0) / 128.0 + dark_fraction + bright_fraction
    technical_score = math.log1p(sharpness) * 20.0 - exposure_penalty * 35.0
    return ImageMetrics(
        dhash=dhash,
        phash=_phash(gray),
        sharpness=round(sharpness, 3),
        brightness=round(brightness, 3),
        dark_fraction=round(dark_fraction, 5),
        bright_fraction=round(bright_fraction, 5),
        technical_score=round(technical_score, 3),
    )


def hamming_distance(left: int, right: int) -> int:
    return (left ^ right).bit_count()


def _seconds_apart(left: dict[str, Any], right: dict[str, Any]) -> float | None:
    left_time = asset_datetime(left)
    right_time = asset_datetime(right)
    if left_time is None or right_time is None:
        return None
    return abs((left_time - right_time).total_seconds())


def select_visual_representatives(
    assets: list[dict[str, Any]],
    metrics: dict[str, ImageMetrics],
    *,
    limit: int = 8,
    similarity_distance: int = 8,
    phash_distance: int = 12,
    sequence_seconds: int = 120,
) -> list[dict[str, Any]]:
    clusters: list[list[dict[str, Any]]] = []
    cluster_hashes: list[int] = []
    cluster_phashes: list[int] = []
    for asset in assets:
        identifier = asset.get("id")
        if not isinstance(identifier, str) or identifier not in metrics:
            continue
        image_hash = metrics[identifier].dhash
        image_phash = metrics[identifier].phash
        match = None
        for index, cluster in enumerate(clusters):
            dhash_match = hamming_distance(image_hash, cluster_hashes[index]) <= similarity_distance
            phash_gap = hamming_distance(image_phash, cluster_phashes[index])
            phash_match = phash_gap <= phash_distance
            seconds = _seconds_apart(asset, cluster[0])
            sequence_match = seconds is not None and seconds <= sequence_seconds and phash_gap <= 20
            if dhash_match or phash_match or sequence_match:
                match = index
                break
        if match is None:
            clusters.append([asset])
            cluster_hashes.append(image_hash)
            cluster_phashes.append(image_phash)
        else:
            clusters[match].append(asset)

    representatives: list[dict[str, Any]] = []
    for cluster in clusters:
        best = max(
            cluster,
            key=lambda asset: (
                asset.get("isFavorite") is True,
                metrics[str(asset.get("id"))].technical_score,
            ),
        )
        identifier = str(best.get("id"))
        representatives.append(
            {
                "id": identifier,
                "type": best.get("type"),
                "taken_at": asset_datetime(best).isoformat() if asset_datetime(best) else None,
                "favorite": bool(best.get("isFavorite", False)),
                "original_path": best.get("originalPath"),
                "visual": metrics[identifier].json(),
                "similar_count": len(cluster),
            }
        )

    representatives.sort(
        key=lambda asset: (asset["favorite"], asset["visual"]["technical_score"]), reverse=True
    )
    selected = representatives[:limit]
    selected.sort(key=lambda asset: asset.get("taken_at") or "")
    return selected


def build_visual_memories(
    assets: list[dict[str, Any]],
    thumbnail_loader: Callable[[str], bytes],
    *,
    event_limit: int = 5,
    max_assets: int = 8,
    similarity_distance: int = 8,
    phash_distance: int = 12,
    sequence_seconds: int = 120,
) -> dict[str, Any]:
    events = [event for event in group_events(assets) if len(event) >= 3]
    events.sort(
        key=lambda event: (
            sum(asset.get("isFavorite") is True for asset in event) * 10 + min(len(event), 20),
            asset_datetime(event[0]).isoformat() if asset_datetime(event[0]) else "",
        ),
        reverse=True,
    )
    output: list[dict[str, Any]] = []
    analyzed = 0
    for event in events[:event_limit]:
        image_assets = [asset for asset in event if asset.get("type") == "IMAGE"]
        metrics: dict[str, ImageMetrics] = {}
        for asset in image_assets:
            identifier = asset.get("id")
            if not isinstance(identifier, str) or not identifier:
                continue
            metrics[identifier] = analyze_image(thumbnail_loader(identifier))
            analyzed += 1
        start = asset_datetime(event[0])
        end = asset_datetime(event[-1])
        output.append(
            {
                "event_id": f"visual-{event[0].get('id')}",
                "start": start.isoformat() if start else None,
                "end": end.isoformat() if end else None,
                "asset_count": len(event),
                "analyzed_images": len(metrics),
                "assets": select_visual_representatives(
                    image_assets,
                    metrics,
                    limit=max_assets,
                    similarity_distance=similarity_distance,
                    phash_distance=phash_distance,
                    sequence_seconds=sequence_seconds,
                ),
            }
        )
    return {
        "policy": {
            "source": "immich_live_timeline_preview_thumbnails",
            "event_limit": event_limit,
            "maximum_representatives": max_assets,
            "similarity_hamming_distance": similarity_distance,
            "phash_hamming_distance": phash_distance,
            "sequence_seconds": sequence_seconds,
            "writes_to_immich": False,
            "persists_thumbnails": False,
        },
        "counts": {"timeline_assets": len(assets), "analyzed_images": analyzed, "memories": len(output)},
        "memories": output,
    }
