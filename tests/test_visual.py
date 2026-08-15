import unittest
from io import BytesIO

from PIL import Image, ImageDraw, ImageFilter

from curator.visual import (
    analyze_image,
    build_visual_memories,
    hamming_distance,
    select_visual_representatives,
)


def image_bytes(kind: str) -> bytes:
    image = Image.new("RGB", (256, 256), "white")
    draw = ImageDraw.Draw(image)
    if kind == "sharp":
        for offset in range(0, 256, 16):
            draw.line((0, offset, 255, 255 - offset), fill="black", width=3)
    elif kind == "similar":
        for offset in range(0, 256, 16):
            draw.line((0, offset, 255, 255 - offset), fill=(8, 8, 8), width=3)
    elif kind == "dark":
        image = Image.new("RGB", (256, 256), (2, 2, 2))
    elif kind == "blurred":
        for offset in range(0, 256, 16):
            draw.line((0, offset, 255, 255 - offset), fill="black", width=3)
        image = image.filter(ImageFilter.GaussianBlur(12))
    output = BytesIO()
    image.save(output, format="JPEG", quality=90)
    return output.getvalue()


class VisualTests(unittest.TestCase):
    def test_sharp_image_scores_above_blurred(self) -> None:
        sharp = analyze_image(image_bytes("sharp"))
        blurred = analyze_image(image_bytes("blurred"))
        self.assertGreater(sharp.sharpness, blurred.sharpness)
        self.assertGreater(sharp.technical_score, blurred.technical_score)

    def test_dark_image_has_exposure_penalty(self) -> None:
        sharp = analyze_image(image_bytes("sharp"))
        dark = analyze_image(image_bytes("dark"))
        self.assertGreater(dark.dark_fraction, 0.9)
        self.assertGreater(sharp.technical_score, dark.technical_score)

    def test_dhash_detects_near_identical_images(self) -> None:
        first = analyze_image(image_bytes("sharp"))
        second = analyze_image(image_bytes("similar"))
        self.assertLessEqual(hamming_distance(first.dhash, second.dhash), 8)

    def test_selection_collapses_similar_and_keeps_favorite(self) -> None:
        metrics = {
            "a": analyze_image(image_bytes("sharp")),
            "b": analyze_image(image_bytes("similar")),
            "c": analyze_image(image_bytes("dark")),
        }
        assets = [
            {"id": "a", "type": "IMAGE", "localDateTime": "2024-01-01T10:00:00"},
            {
                "id": "b",
                "type": "IMAGE",
                "localDateTime": "2024-01-01T10:01:00",
                "isFavorite": True,
            },
            {"id": "c", "type": "IMAGE", "localDateTime": "2024-01-01T11:00:00"},
        ]
        selected = select_visual_representatives(assets, metrics, limit=3)
        self.assertEqual([asset["id"] for asset in selected], ["b", "c"])
        self.assertEqual(selected[0]["similar_count"], 2)

    def test_selection_collapses_a_short_burst_even_when_images_differ(self) -> None:
        metrics = {
            "a": analyze_image(image_bytes("sharp")),
            "b": analyze_image(image_bytes("dark")),
        }
        assets = [
            {"id": "a", "type": "IMAGE", "localDateTime": "2024-01-01T10:00:00"},
            {"id": "b", "type": "IMAGE", "localDateTime": "2024-01-01T10:00:10"},
        ]
        selected = select_visual_representatives(assets, metrics, limit=2)
        self.assertEqual(len(selected), 1)
        self.assertEqual(selected[0]["similar_count"], 2)

    def test_center_crop_phashes_are_recorded(self) -> None:
        metrics = analyze_image(image_bytes("sharp"))
        self.assertEqual(len(metrics.crop_phashes), 2)
        self.assertEqual(len(metrics.json()["crop_phashes"]), 2)

    def test_build_visual_memories_uses_thumbnail_loader(self) -> None:
        assets = [
            {
                "id": identifier,
                "type": "IMAGE",
                "localDateTime": f"2024-01-01T10:0{index}:00",
            }
            for index, identifier in enumerate(("a", "b", "c"))
        ]
        images = {"a": image_bytes("sharp"), "b": image_bytes("similar"), "c": image_bytes("dark")}
        result = build_visual_memories(assets, images.__getitem__)
        self.assertEqual(result["counts"]["analyzed_images"], 3)
        self.assertEqual(result["counts"]["memories"], 1)
        self.assertFalse(result["policy"]["persists_thumbnails"])


if __name__ == "__main__":
    unittest.main()
