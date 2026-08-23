import json
import tempfile
import unittest
from pathlib import Path

from curator.webapp import FeedbackStore, SuggestionApplication


class FakeClient:
    def __init__(self):
        self.albums = {}

    def iter_timeline_assets(self):
        return iter([{"id": "a"}, {"id": "b"}])

    def find_owned_albums(self, name):
        return [value for value in self.albums.values() if value["albumName"] == name]

    def create_album(self, name, description):
        album = {"id": "album-1", "albumName": name, "assets": []}
        self.albums[album["id"]] = album
        return album

    def add_assets_to_album(self, album_id, asset_ids):
        self.albums[album_id]["assets"].extend(asset_ids)

    def iter_album_assets(self, album_id):
        return iter({"id": value} for value in self.albums[album_id]["assets"])


class WebAppTests(unittest.TestCase):
    def test_feedback_is_persisted_atomically(self):
        with tempfile.TemporaryDirectory() as directory:
            store = FeedbackStore(Path(directory) / "feedback.json")
            store.set_status("event-1", "held")
            self.assertEqual(store.read()["events"]["event-1"]["status"], "held")

    def test_review_album_is_created_for_one_suggestion(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "suggestions.json"
            source.write_text(json.dumps({"memories": [{
                "event_id": "event-1",
                "start": "2024-01-01T10:00:00+00:00",
                "assets": [{"id": "a"}, {"id": "b"}],
            }]}), encoding="utf-8")
            app = SuggestionApplication(FakeClient(), source, root / "feedback.json", immich_public_url="https://immich.test")
            result = app.create_review("event-1")
            self.assertTrue(result["verified"])
            self.assertEqual(result["immich_url"], "https://immich.test/albums/album-1")
            self.assertEqual(app.feedback.read()["events"]["event-1"]["status"], "review_album_created")


if __name__ == "__main__":
    unittest.main()
