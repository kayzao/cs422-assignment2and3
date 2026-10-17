
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from netlab.runner import run_experiment
from netlab.transfer import TransferError


class RunnerTests(unittest.TestCase):


    def test_replacement_preserves_partial_runs_and_accepts_only_complete_sets(self):

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            servers = root / "servers.csv"
            servers.write_text("host,port\na.example,5201\nb.example,5201\n")
            args = SimpleNamespace(servers=servers, destinations=1, algorithms=["cubic"],
                                   duration=1, interval=0.2, repetitions=2, seed=422,
                                   max_attempts=2, timeout=1, drain_timeout=1,
                                   stall_timeout=2, pause=0, backoff=0, output=root / "results")
            calls = 0



            def fake_transfer(run, *unused, **kwargs):
                nonlocal calls
                calls += 1
                if calls == 2:
                    result = {"protocol_complete": False, "failure_stage": "parameter_exchange",
                              "error": "synthetic rejection"}
                    raise TransferError("parameter_exchange", RuntimeError("synthetic rejection"), result)
                return {"protocol_complete": True, "algorithm_actual": "cubic"}


            with patch("netlab.runner.check_environment", return_value={}), \
                    patch("netlab.runner.run_transfer", side_effect=fake_transfer), \
                    patch("netlab.analysis.ensure_plotting"), patch("netlab.analysis.analyze_results"):
                output, incomplete = run_experiment(args, root)

            manifest = json.loads((output / "manifest.json").read_text())
            self.assertFalse(incomplete)
            self.assertEqual(len(manifest["attempts"]), 2)
            self.assertEqual(manifest["attempts"][0]["status"], "failed")
            self.assertEqual([run["accepted"] for run in manifest["runs"]], [False, False, True, True])
            self.assertEqual(manifest["destination_shortfall"], 0)
            self.assertEqual(manifest["representative_destination"], manifest["successful_destinations"][0])
            self.assertEqual(manifest["server_list"]["name"], "servers.csv")
            self.assertNotIn(str(root), (output / "manifest.json").read_text())


    def test_attempt_limit_reports_shortfall_and_no_measured_plots(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            args = self.configuration(root)
            failure = TransferError("control_connect", TimeoutError("synthetic timeout"),
                                    {"protocol_complete": False, "failure_stage": "control_connect",
                                     "error": "synthetic timeout"})
            with patch("netlab.runner.check_environment", return_value={}), \
                    patch("netlab.runner.run_transfer", side_effect=failure) as transfer, \
                    patch("netlab.analysis.ensure_plotting"):
                output, incomplete = run_experiment(args, root)
            manifest = json.loads((output / "manifest.json").read_text())
            self.assertTrue(incomplete)
            self.assertEqual(transfer.call_count, 2)
            self.assertEqual(manifest["status"], "shortfall")
            self.assertEqual(manifest["destination_shortfall"], 1)
            self.assertIsNone(manifest["representative_destination"])
            self.assertEqual(len(manifest["attempts"]), 2)
            self.assertTrue(all(run["status"] == "failed" for run in manifest["runs"]))
            self.assertFalse(list((output / "plots").glob("*.pdf")))
            self.assertEqual(len((output / "summary.csv").read_text().splitlines()), 1)

    def test_interruption_finalizes_pending_run_and_attempt(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            args = self.configuration(root)
            with patch("netlab.runner.check_environment", return_value={}), \
                    patch("netlab.runner.run_transfer", side_effect=KeyboardInterrupt), \
                    patch("netlab.analysis.ensure_plotting"):
                output, incomplete = run_experiment(args, root)
            manifest = json.loads((output / "manifest.json").read_text())
            self.assertTrue(incomplete)
            self.assertEqual(manifest["status"], "interrupted")
            self.assertEqual(manifest["attempts"][0]["status"], "interrupted")
            self.assertEqual(manifest["runs"][0]["status"], "interrupted")
            self.assertFalse(manifest["runs"][0]["accepted"])
            run = json.loads((output / "runs" / "run-0001.json").read_text())
            self.assertEqual(run["status"], "interrupted")

    @staticmethod
    def configuration(root):
        servers = root / "servers.csv"
        servers.write_text("host,port\na.example,5201\nb.example,5201\n")
        return SimpleNamespace(servers=servers, destinations=1, algorithms=["cubic"],
                               duration=1, interval=0.2, repetitions=1, seed=422,
                               max_attempts=2, timeout=1, drain_timeout=1,
                               stall_timeout=2, pause=0, backoff=0, output=root / "results")


if __name__ == "__main__":
    unittest.main()
