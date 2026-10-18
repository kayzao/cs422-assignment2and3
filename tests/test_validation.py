import unittest

from netlab.validation import PAYLOAD_BLOCK_SIZE, assess_byte_count, validation_report


class ByteCountTests(unittest.TestCase):
    def test_exact_and_only_final_partial_block_are_accepted(self):
        sent = 2 * PAYLOAD_BLOCK_SIZE + 123
        self.assertEqual(assess_byte_count(sent, sent)["status"], "exact")
        check = assess_byte_count(sent, 2 * PAYLOAD_BLOCK_SIZE)
        self.assertEqual(check["status"], "partial_block")
        self.assertEqual(check["missing_bytes"], 123)
        for received in [sent - 1, PAYLOAD_BLOCK_SIZE, sent + 1]:
            with self.subTest(received=received):
                self.assertEqual(assess_byte_count(sent, received)["status"], "mismatch")

    def test_malformed_receiver_counts_are_rejected(self):
        for received in [True, False, None, "12", 0, -1, 1.5, float("nan"), float("inf")]:
            with self.subTest(received=received):
                self.assertEqual(assess_byte_count(100, received)["status"], "mismatch")
        self.assertEqual(assess_byte_count(100, 100.0)["status"], "exact")

    def test_legacy_runs_are_audited_without_rewriting_acceptance(self):
        runs = [{"run_id": "exact", "status": "complete", "accepted": True,
                 "payload_bytes_sent": 100, "server_payload_bytes_received": 100},
                {"run_id": "tail", "status": "complete", "accepted": True,
                 "payload_bytes_sent": PAYLOAD_BLOCK_SIZE + 123,
                 "server_payload_bytes_received": PAYLOAD_BLOCK_SIZE},
                {"run_id": "bad", "status": "complete", "accepted": True,
                 "payload_bytes_sent": 1000, "server_payload_bytes_received": 1},
                {"run_id": "excluded", "status": "complete", "accepted": False},
                {"run_id": "failed", "status": "failed", "failure_stage": "payload_drain",
                 "pending_payload_bytes": 100, "last_payload_snapshot": {"notsent_bytes": 50}}]
        report = validation_report({"runs": runs})
        self.assertEqual(report["status"], "review_required")
        self.assertEqual(report["accepted_runs"], 3)
        self.assertEqual(report["byte_count_warnings"], 1)
        self.assertEqual(report["byte_count_errors"], 1)
        self.assertEqual(report["completed_but_excluded_runs"], ["excluded"])
        self.assertEqual(report["failure_counts_by_stage"], {"payload_drain": 1})
        self.assertEqual(report["failed_runs"][0]["pending_payload_bytes"], 100)
        self.assertTrue(runs[2]["accepted"])
        self.assertEqual(validation_report({"runs": []})["status"], "review_required")


if __name__ == "__main__":
    unittest.main()
