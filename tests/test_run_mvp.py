import json
import tempfile
import unittest
from pathlib import Path

from scripts.run_mvp import build_cards, load_records


ROOT = Path(__file__).resolve().parents[1]


class RidePulseMvpTests(unittest.TestCase):
    def test_verified_sample_loads(self):
        records = load_records(ROOT / "data" / "verified_evidence_sample.json")
        self.assertGreaterEqual(len(records), 7)
        self.assertEqual(len(records), len({row["evidence_id"] for row in records}))

    def test_single_platform_cluster_is_not_overclaimed(self):
        records = load_records(ROOT / "data" / "verified_evidence_sample.json")
        cards = build_cards(records)
        firmware = next(card for card in cards if card["theme"] == "firmware_stability")
        self.assertEqual(firmware["confidence"], "low")
        self.assertTrue(firmware["human_review_required"])

    def test_invalid_url_is_rejected(self):
        records = json.loads((ROOT / "data" / "verified_evidence_sample.json").read_text(encoding="utf-8"))
        records[0]["source_url"] = "example.com/no-scheme"
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "bad.json"
            path.write_text(json.dumps(records), encoding="utf-8")
            with self.assertRaises(ValueError):
                load_records(path)


if __name__ == "__main__":
    unittest.main()

