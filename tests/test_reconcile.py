import unittest

from curator.reconcile import normalize_path, photoprism_path, reconcile


class ReconcileTests(unittest.TestCase):
    def test_normalize_known_roots(self) -> None:
        self.assertEqual(
            normalize_path("/data/library/admin/2021/a.jpg"), "library/admin/2021/a.jpg"
        )
        self.assertEqual(
            normalize_path("/photoprism/originals/library/admin/2021/a.jpg"),
            "library/admin/2021/a.jpg",
        )

    def test_photoprism_path_combines_directory_and_name(self) -> None:
        self.assertEqual(
            photoprism_path({"Path": "library/admin/2021", "Name": "a.jpg"}),
            "library/admin/2021/a.jpg",
        )

    def test_reconcile_only_emits_exact_timeline_path_matches(self) -> None:
        immich = [
            {
                "id": "asset-1",
                "originalPath": "/data/library/admin/2021/a.jpg",
                "type": "IMAGE",
                "isFavorite": True,
                "exifInfo": {"latitude": 35.0, "longitude": 139.0},
            },
            {"id": "asset-2", "originalPath": "/data/library/admin/2021/same.jpg"},
        ]
        photos = [
            {
                "UID": "photo-1",
                "ID": "composite-1",
                "Path": "library/admin/2021",
                "Name": "a.jpg",
                "Quality": 4,
                "Labels": [{"Name": "Person"}],
            },
            {"UID": "wrong", "Path": "library/admin/2020", "Name": "same.jpg"},
        ]

        result = reconcile(immich, photos)

        self.assertEqual(
            result["counts"],
            {
                "immich_timeline": 2,
                "photoprism_indexed": 2,
                "matched": 1,
                "immich_unmatched": 1,
                "photoprism_unmatched": 1,
                "photoprism_duplicate_paths": 0,
            },
        )
        self.assertEqual(result["candidates"][0]["immich"]["id"], "asset-1")
        self.assertEqual(result["candidates"][0]["photoprism"]["uid"], "photo-1")


if __name__ == "__main__":
    unittest.main()
