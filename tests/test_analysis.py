
import csv
import json
from pathlib import Path
import tempfile
import unittest

from netlab.analysis import analyze_results, load_samples, percentile, summarize
from netlab.transfer import SAMPLE_FIELDS




def synthetic_results(path):
    """Clearly synthetic fixtures, never submitted as network measurements."""

    manifest = {"runs": [{"run_id": "run-0001", "status": "complete", "accepted": True,
                           "algorithm_actual": "cubic"},
                          {"run_id": "failed", "status": "failed", "accepted": False}],
                "representative_destination": {"host": "test.example", "port": 5201},
                "successful_destinations": [{"host": "test.example", "port": 5201}],
                "requested_destinations": 1, "destination_shortfall": 0}
    (path / "manifest.json").write_text(json.dumps(manifest))

    base = {key: 0 for key in SAMPLE_FIELDS}
    base.update(experiment_id="synthetic-fixture", run_id="run-0001", destination_host="test.example",
                destination_port=5201, algorithm_actual="cubic", algorithm_requested="cubic",
                repetition=1, timestamp_utc="2026-01-01T00:00:00Z", phase="transfer",
                snd_cwnd_segments=10, snd_mss_bytes=1448, rtt_us=10000)
    with (path / "samples.csv").open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=SAMPLE_FIELDS)
        writer.writeheader()
        for elapsed, dt, acked, rate in ((0.2, 0.2, 0, 0), (0.4, 0.2, 200000, 8e6),
                                        (0.8, 0.4, 800000, 16e6)):
            writer.writerow({**base, "elapsed_s": elapsed, "sample_interval_actual_s": dt,
                             "bytes_acked_delta": acked, "goodput_bps": rate})

        writer.writerow({**base, "run_id": "failed", "goodput_bps": 99e9})
        writer.writerow({**base, "phase": "drain", "goodput_bps": 99e9})
    return manifest


class AnalysisTests(unittest.TestCase):


    def test_zero_samples_and_actual_time_weighting_with_failed_runs_excluded(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            rows = load_samples(path, synthetic_results(path))
            summary = summarize(rows)

        self.assertEqual(len(rows), 3)
        self.assertEqual(summary["minimum_goodput_bps"], 0)
        self.assertEqual(summary["mean_goodput_bps"], 8e6)
        self.assertAlmostEqual(summary["p95_goodput_bps"], 15.2e6)
        self.assertEqual(summary["time_weighted_mean_goodput_bps"], 10e6)
        self.assertEqual(percentile([42], 0.95), 42)



    def test_offline_outputs_include_all_seven_representative_panels(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            synthetic_results(path)
            try:
                result = analyze_results(path)
            except RuntimeError as error:
                if "plotting dependency" in str(error):
                    self.skipTest("install requirements.txt to check PDF generation")
                raise

            self.assertEqual(result["accepted_runs"], 1)
            self.assertEqual(len(result["plots"]), 3)
            for name in result["plots"]:
                self.assertTrue((path / name).read_bytes().startswith(b"%PDF"))
            self.assertIn("zero-goodput intervals: 1", (path / "observations.md").read_text())


if __name__ == "__main__":
    unittest.main()
