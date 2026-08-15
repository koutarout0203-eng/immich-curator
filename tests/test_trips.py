import unittest

from curator.trips import (
    build_home_candidates,
    build_trip_candidates,
    create_trip_candidate_album,
    create_all_trip_candidate_albums,
    distance_km,
    normalize_home_periods,
    prune_stale_trip_albums,
)


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
        self.albums = {}

    def find_owned_albums(self, name):
        if self.existing:
            return [{"id": "existing"}]
        return [{"id": album_id} for album_id, album in self.albums.items() if album["name"] == name]

    def create_album(self, name, description):
        album_id = f"trip-album-{len(self.albums) + 1}"
        self.albums[album_id] = {"name": name, "assets": []}
        return {"id": album_id, "albumName": name}

    def add_assets_to_album(self, album_id, asset_ids):
        self.added = list(asset_ids)
        if album_id in self.albums:
            current = self.albums[album_id]["assets"]
            current.extend(identifier for identifier in asset_ids if identifier not in current)

    def iter_album_assets(self, album_id):
        if album_id in self.albums:
            return iter({"id": identifier} for identifier in self.albums[album_id]["assets"])
        return iter({"id": identifier} for identifier in self.added)

    def delete_album(self, album_id):
        self.albums.pop(album_id, None)


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
            trip_padding_hours=24,
        )
        self.assertEqual(result["counts"]["trip_candidates"], 1)
        trip = result["trips"][0]
        self.assertEqual(trip["inferred_asset_count"], 2)
        rows = {row["id"]: row for row in trip["assets"]}
        self.assertEqual(rows["camera-near"]["inference_confidence"], "high")
        self.assertEqual(rows["camera-mid"]["inference_confidence"], "medium")

    def test_trip_bounds_exclude_home_photos_outside_anchor_padding(self):
        assets = [
            asset("home-before", "2024-07-07T05:00:00", 35.0, 139.0, "Home"),
            asset("away-1", "2024-07-07T10:00:00", 36.2, 138.7, "Away"),
            asset("camera", "2024-07-07T11:00:00"),
            asset("away-2", "2024-07-07T18:00:00", 36.2, 138.7, "Away"),
            asset("home-after", "2024-07-07T23:00:00", 35.0, 139.0, "Home"),
        ]
        result = build_trip_candidates(
            assets,
            home=(35.0, 139.0),
            minimum_anchors=2,
            minimum_assets=1,
            trip_padding_hours=3,
        )
        identifiers = [row["id"] for row in result["trips"][0]["assets"]]
        self.assertEqual(identifiers, ["away-1", "camera", "away-2"])

    def test_home_candidates_use_recurring_days_and_detect_a_move(self):
        assets = []
        for month in range(1, 7):
            assets.append(asset(f"old-{month}-a", f"2024-{month:02d}-05T21:00:00", 35.0, 139.0, "Old Home"))
            assets.append(asset(f"old-{month}-b", f"2024-{month:02d}-20T08:00:00", 35.0, 139.0, "Old Home"))
        for month in range(7, 13):
            assets.append(asset(f"new-{month}-a", f"2024-{month:02d}-05T21:00:00", 34.7, 135.5, "New Home"))
            assets.append(asset(f"new-{month}-b", f"2024-{month:02d}-20T08:00:00", 34.7, 135.5, "New Home"))
        for index in range(100):
            assets.append(asset(f"trip-{index}", "2024-03-10T12:00:00", 33.0, 130.5, "Trip"))
        result = build_home_candidates(assets, window_months=6)
        self.assertEqual(result["counts"]["suggested_home_periods"], 2)
        periods = result["suggested_home_periods"]
        self.assertAlmostEqual(periods[0]["latitude"], 35.0)
        self.assertAlmostEqual(periods[1]["longitude"], 135.5)
        self.assertEqual(periods[0]["location_label"], "Old Home, Japan")
        self.assertFalse(result["policy"]["automatically_applied_to_trips"])

    def test_trips_use_the_home_active_at_capture_time(self):
        periods = normalize_home_periods(
            {
                "suggested_home_periods": [
                    {"start": "2024-01-01", "end": "2024-03-31", "latitude": 35.0, "longitude": 139.0, "location_label": "Old"},
                    {"start": "2024-04-01", "end": "2024-12-31", "latitude": 34.7, "longitude": 135.5, "location_label": "New"},
                ]
            }
        )
        assets = [
            asset("old-home", "2024-02-01T10:00:00", 35.0, 139.0, "Old"),
            asset("old-trip", "2024-02-10T10:00:00", 36.2, 138.7, "Away"),
            asset("new-home", "2024-05-01T10:00:00", 34.7, 135.5, "New"),
            asset("new-trip", "2024-05-10T10:00:00", 35.36, 138.73, "Fuji"),
        ]
        result = build_trip_candidates(
            assets,
            home_periods=periods,
            minimum_anchors=1,
            minimum_assets=1,
        )
        self.assertEqual(result["counts"]["trip_candidates"], 2)
        self.assertEqual(
            {trip["home_period"]["location_label"] for trip in result["trips"]},
            {"Old", "New"},
        )

    def test_home_periods_must_not_overlap(self):
        with self.assertRaisesRegex(ValueError, "overlap"):
            normalize_home_periods(
                {
                    "homes": [
                        {"start": "2024-01-01", "end": "2024-06-30", "latitude": 1, "longitude": 1},
                        {"start": "2024-06-01", "end": None, "latitude": 2, "longitude": 2},
                    ]
                }
            )

    def test_single_home_photo_does_not_split_a_continuing_trip(self):
        periods = normalize_home_periods(
            {"homes": [{"start": "2024-01-01", "end": None, "latitude": 35.0, "longitude": 139.0, "name": "Home"}]}
        )
        assets = [
            asset("away-saturday", "2024-05-04T12:00:00", 36.2, 138.7, "Away A"),
            asset("home-night", "2024-05-04T23:00:00", 35.0, 139.0, "Home"),
            asset("away-sunday", "2024-05-05T12:00:00", 35.8, 140.5, "Away B"),
        ]
        result = build_trip_candidates(
            assets,
            home_periods=periods,
            minimum_anchors=1,
            minimum_assets=1,
        )
        self.assertEqual(result["counts"]["trip_candidates"], 1)
        self.assertFalse(result["policy"]["splits_on_detected_home_return"])

    def test_trip_album_is_created_once_and_verified(self):
        trip_data = {
            "trips": [{
                "trip_id": "trip-1",
                "suggested_album_name": "2024-01-01 - Trip Candidate - Test",
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

    def test_bulk_trip_albums_are_idempotent(self):
        data = {
            "trips": [
                {"trip_id": "one", "suggested_album_name": "2024-01-01 - Trip Candidate - One", "assets": [{"id": "a"}]},
                {"trip_id": "two", "suggested_album_name": "2024-02-01 - Trip Candidate - Two", "assets": [{"id": "b"}]},
            ]
        }
        client = FakeClient()
        first = create_all_trip_candidate_albums(client, data, apply=True, live_timeline_ids={"a", "b"})
        second = create_all_trip_candidate_albums(client, data, apply=True, live_timeline_ids={"a", "b"})
        self.assertEqual(first["counts"]["created"], 2)
        self.assertEqual(second["counts"]["skipped_verified"], 2)
        self.assertEqual(
            {album["name"] for album in client.albums.values()},
            {"2024-01-01 - Trip - One", "2024-02-01 - Trip - Two"},
        )

    def test_bulk_trip_albums_can_repair_strict_subsets_additively(self):
        data = {
            "trips": [{
                "trip_id": "one",
                "suggested_album_name": "2024-01-01 - Trip Candidate - One",
                "assets": [{"id": "a"}, {"id": "b"}],
            }]
        }
        client = FakeClient()
        album = client.create_album("2024-01-01 - Trip - One", "old")
        client.add_assets_to_album(album["id"], ["a"])
        result = create_all_trip_candidate_albums(
            client,
            data,
            apply=True,
            live_timeline_ids={"a", "b"},
            add_missing_to_conflicts=True,
        )
        self.assertEqual(result["counts"]["repaired_additive"], 1)
        self.assertEqual(set(client.albums[album["id"]]["assets"]), {"a", "b"})

    def test_bulk_trip_albums_does_not_repair_when_existing_has_extras(self):
        data = {
            "trips": [{
                "trip_id": "one",
                "suggested_album_name": "2024-01-01 - Trip Candidate - One",
                "assets": [{"id": "a"}, {"id": "b"}],
            }]
        }
        client = FakeClient()
        album = client.create_album("2024-01-01 - Trip - One", "old")
        client.add_assets_to_album(album["id"], ["a", "extra"])
        result = create_all_trip_candidate_albums(
            client,
            data,
            apply=True,
            live_timeline_ids={"a", "b", "extra"},
            add_missing_to_conflicts=True,
        )
        self.assertEqual(result["counts"]["conflict"], 1)
        self.assertEqual(set(client.albums[album["id"]]["assets"]), {"a", "extra"})

    def test_prune_deletes_only_exact_old_album_covered_by_current_trip(self):
        previous = {"trips": [{
            "trip_id": "old",
            "suggested_album_name": "2024-01-02 - Trip Candidate - Split",
            "assets": [{"id": "a"}],
        }]}
        current = {"trips": [{
            "trip_id": "new",
            "suggested_album_name": "2024-01-01 - Trip Candidate - Merged",
            "assets": [{"id": "a"}, {"id": "b"}],
        }]}
        client = FakeClient()
        album = client.create_album("2024-01-02 - Trip - Split", "old")
        client.add_assets_to_album(album["id"], ["a"])
        result = prune_stale_trip_albums(client, previous, current, apply=True)
        self.assertEqual(result["counts"]["deleted"], 1)
        self.assertEqual(result["assets_deleted"], 0)
        self.assertFalse(client.albums)

    def test_prune_refuses_live_album_membership_mismatch(self):
        previous = {"trips": [{
            "trip_id": "old",
            "suggested_album_name": "2024-01-02 - Trip Candidate - Split",
            "assets": [{"id": "a"}],
        }]}
        current = {"trips": [{
            "trip_id": "new",
            "suggested_album_name": "2024-01-01 - Trip Candidate - Merged",
            "assets": [{"id": "a"}, {"id": "b"}],
        }]}
        client = FakeClient()
        album = client.create_album("2024-01-02 - Trip - Split", "old")
        client.add_assets_to_album(album["id"], ["a", "extra"])
        result = prune_stale_trip_albums(client, previous, current, apply=True)
        self.assertEqual(result["counts"]["conflict"], 1)
        self.assertIn(album["id"], client.albums)


if __name__ == "__main__":
    unittest.main()
