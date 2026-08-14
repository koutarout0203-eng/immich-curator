import unittest

from curator.memories import build_memories, group_events, select_representatives


def asset(identifier: str, taken: str, *, favorite: bool = False) -> dict:
    return {
        "id": identifier,
        "type": "IMAGE",
        "localDateTime": taken,
        "isFavorite": favorite,
        "originalPath": f"/data/library/admin/2024/{identifier}.jpg",
    }


class MemoryTests(unittest.TestCase):
    def test_splits_events_after_gap(self) -> None:
        events = group_events(
            [
                asset("a", "2024-01-01T10:00:00+09:00"),
                asset("b", "2024-01-01T12:00:00+09:00"),
                asset("c", "2024-01-02T08:00:00+09:00"),
            ]
        )
        self.assertEqual([[item["id"] for item in event] for event in events], [["a", "b"], ["c"]])

    def test_representatives_keep_favorite_and_spread_others(self) -> None:
        assets = [asset(str(index), f"2024-01-01T{index:02}:00:00+09:00") for index in range(10)]
        assets[5]["isFavorite"] = True
        selected = select_representatives(assets, 4)
        self.assertIn("5", [item["id"] for item in selected])
        self.assertEqual(len(selected), 4)

    def test_builds_read_only_memory_contract(self) -> None:
        result = build_memories(
            [
                asset("a", "2024-01-01T10:00:00+09:00"),
                asset("b", "2024-01-01T10:05:00+09:00", favorite=True),
                asset("c", "2024-01-01T10:10:00+09:00"),
            ]
        )
        self.assertEqual(result["counts"]["memory_suggestions"], 1)
        self.assertEqual(result["counts"]["eligible_memories"], 1)
        self.assertFalse(result["policy"]["writes_to_immich"])
        self.assertEqual(result["memories"][0]["favorite_count"], 1)


if __name__ == "__main__":
    unittest.main()
