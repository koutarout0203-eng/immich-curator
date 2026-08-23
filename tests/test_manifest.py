import unittest

from curator.manifest import build_trip_manifest


class FakeClient:
    def find_owned_albums(self, name):
        return [{"id": "album-1", "albumName": name}] if "Linked" in name else []


class ManifestTests(unittest.TestCase):
    def test_manifest_contains_links_but_no_secrets_or_binaries(self):
        data = {"trips": [{
            "trip_id": "trip-1",
            "suggested_album_name": "2024-01-01 - Trip Candidate - Linked",
            "start": "2024-01-01T00:00:00+00:00",
            "end": "2024-01-02T00:00:00+00:00",
            "label": "Linked",
            "assets": [{"id": "asset-1"}, {"id": "asset-2"}],
        }]}
        result = build_trip_manifest(FakeClient(), data, immich_public_url="https://immich.test")
        self.assertEqual(result["schema_version"], 1)
        self.assertFalse(result["contains_secrets"])
        self.assertFalse(result["contains_photo_binaries"])
        self.assertEqual(result["trips"][0]["album"]["url"], "https://immich.test/albums/album-1")
        self.assertEqual(result["trips"][0]["cover_asset_id"], "asset-1")


if __name__ == "__main__":
    unittest.main()
