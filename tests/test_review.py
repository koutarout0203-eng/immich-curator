import unittest

from curator.review import create_review_album, review_asset_ids


MEMORIES = {
    "memories": [
        {"assets": [{"id": "a"}, {"id": "b"}]},
        {"assets": [{"id": "b"}, {"id": "c"}]},
    ]
}


class FakeClient:
    def __init__(self) -> None:
        self.created = False
        self.added: list[str] = []

    def find_owned_albums(self, name):
        return []

    def create_album(self, name, description):
        self.created = True
        return {"id": "album-1", "albumName": name}

    def add_assets_to_album(self, album_id, asset_ids):
        self.added = list(asset_ids)

    def get_album(self, album_id):
        return {"id": album_id, "assets": [{"id": identifier} for identifier in self.added]}


class ReviewTests(unittest.TestCase):
    def test_deduplicates_assets_across_events(self) -> None:
        self.assertEqual(review_asset_ids(MEMORIES, 5, 60), ["a", "b", "c"])

    def test_dry_run_does_not_call_client(self) -> None:
        result = create_review_album(None, MEMORIES, name="Review")  # type: ignore[arg-type]
        self.assertEqual(result["mode"], "dry-run")
        self.assertEqual(result["asset_count"], 3)

    def test_apply_creates_adds_and_verifies(self) -> None:
        client = FakeClient()
        result = create_review_album(client, MEMORIES, name="Review", apply=True)
        self.assertTrue(client.created)
        self.assertEqual(client.added, ["a", "b", "c"])
        self.assertTrue(result["verified"])


if __name__ == "__main__":
    unittest.main()
