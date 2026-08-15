import unittest

from curator.clients import ImmichClient, PhotoPrismClient


class FakeImmich(ImmichClient):
    def __init__(self, responses):
        super().__init__("http://immich", "key")
        self.responses = iter(responses)

    def _json_request(self, *args, **kwargs):
        self.last_request = (args, kwargs)
        return next(self.responses), {}


class FakePhotoPrism(PhotoPrismClient):
    def __init__(self, responses):
        super().__init__("http://photoprism", "token")
        self.responses = iter(responses)

    def _json_request(self, *args, **kwargs):
        return next(self.responses)


class ClientTests(unittest.TestCase):
    def test_immich_timeline_pagination_and_defensive_archive_filter(self) -> None:
        client = FakeImmich(
            [
                {
                    "assets": {
                        "items": [{"id": "a"}, {"id": "hidden", "isArchived": True}],
                        "nextPage": "2",
                    }
                },
                {"assets": {"items": [{"id": "b"}], "nextPage": None}},
            ]
        )
        self.assertEqual([asset["id"] for asset in client.iter_timeline_assets()], ["a", "b"])
        self.assertTrue(client.last_request[0][3]["withPeople"])

    def test_photoprism_header_pagination(self) -> None:
        client = FakePhotoPrism(
            [
                ([{"UID": "a"}, {"UID": "b"}], {"x-count": "2", "x-limit": "2"}),
                ([{"UID": "c"}], {"x-count": "1", "x-limit": "2"}),
            ]
        )
        self.assertEqual(
            [photo["UID"] for photo in client.iter_photos(page_size=2)], ["a", "b", "c"]
        )

    def test_album_asset_search_pagination(self) -> None:
        client = FakeImmich(
            [
                {"assets": {"items": [{"id": "a"}], "nextPage": 2}},
                {"assets": {"items": [{"id": "b"}], "nextPage": None}},
            ]
        )
        self.assertEqual(
            [asset["id"] for asset in client.iter_album_assets("album-1")], ["a", "b"]
        )


if __name__ == "__main__":
    unittest.main()
