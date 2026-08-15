import unittest

from curator.trips import build_trip_candidates, create_trip_candidate_album, distance_km


def asset(identifier, taken, latitude=None, longitude=None, city=None):
    exif = {}
    if latitude is not None:
        exif.update({"latitude": latitude, "longitude": longitude, "city": city, "country": "Japan"})
    return {
        "id": identifier,
        "type": "IMAGE",
        "localDateTime": taken,
        "originalPath": f"/library/{identifier}.jpg",
        "exifInfo": exif,
    }


class FakeClient:
    def __init__(self, existing=False):
        self.existing = existing
        self.added = []

    def find_owned_albums(self, name):
        return [{"id": "existing"}] if self.existing else []

    def create_album(self, name, description):
        return {"id": "trip-album", "albumName": name}

    def add_assets_to_album(self, album_id, asset_ids):
        self.added = list(asset_ids)

    def iter_album_assets(self, album_id):
        return iter({"id": identifier} for identifier in self.added)


class TripTests(unittest.TestCase):
    def test_distance_is_geographic(self):
        self.assertGreater(distance_km((35.68, 139.76), (35.36, 138.73)), 90)

    def test_trip_includes_gps_free_camera_assets_and_confidence(self):
        assets = [
            asset("home-1", "2024-07-01T10:00:00", 35.68, 139.76, "Tokyo"),
            asset("home-2", "2024-07-02T10:00:00", 35.68, 139.76, "Tokyo"),
            asset("g1", "2024-07-07T09:00:00", 35.36, 138.73, "Fujikawaguchiko"),
            asset("camera-near", "2024-07-07T09:10:00"),
            asset("g2", "2024-07-07T12:00:00", 35.40, 138.75, "Fujikawaguchiko"),
            asset("camera-mid", "2024-07-07T16:00:00"),
            asset("g3", "2024-07-08T09:00:00", 35.42, 138.76, "Fujikawaguchiko"),
        ]
        result = build_trip_candidates(
            assets,
            home=(35.68, 139.76),
            minimum_assets=5,
        )
        self.assertEqual(result["counts"]["trip_candidates"], 1)
        trip = result["trips"][0]
        self.assertEqual(trip["inferred_asset_count"], 2)
        rows = {row["id"]: row for row in trip["assets"]}
        self.assertEqual(rows["camera-near"]["inference_confidence"], "high")
        self.assertEqual(rows["camera-mid"]["inference_confidence"], "medium")

    def test_trip_album_is_created_once_and_verified(self):
        trip_data = {
            "trips": [{
                "trip_id": "trip-1",
                "suggested_album_name": "Trip Candidate - Test - 2024-01-01",
                "assets": [{"id": "a"}, {"id": "b"}],
            }]
        }
        client = FakeClient()
        result = create_trip_candidate_album(
            client,
            trip_data,
            trip_id="trip-1",
            apply=True,
            live_timeline_ids={"a", "b"},
        )
        self.assertTrue(result["verified"])
        self.assertTrue(result["immutable_by_convention"])
        with self.assertRaisesRegex(ValueError, "immutable"):
            create_trip_candidate_album(
                FakeClient(existing=True),
                trip_data,
                trip_id="trip-1",
                apply=True,
                live_timeline_ids={"a", "b"},
            )


if __name__ == "__main__":
    unittest.main()
