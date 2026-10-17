import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


class PlanCliTests(unittest.TestCase):
    def test_default_server_list_and_json_output_from_another_directory(self):
        # Exercise the public entry point: its default CSV must resolve beside
        # the script, and the schedule must actually reach standard output.
        script = Path(__file__).resolve().parents[1] / "run.py"
        with tempfile.TemporaryDirectory() as directory:
            completed = subprocess.run(
                [sys.executable, str(script), "plan", "--destinations", "2",
                 "--duration", "10", "--interval", "0.2", "--repetitions", "3",
                 "--algorithms", "cubic", "reno", "bbr"],
                cwd=directory, capture_output=True, text=True, check=True,
            )
        plan = json.loads(completed.stdout)
        self.assertEqual(plan["status"], "planned_only")
        self.assertEqual(len(plan["selected_destinations"]), 2)
        self.assertEqual(len(plan["runs"]), 18)
        self.assertEqual(plan["active_transfer_seconds"], 180)
        self.assertEqual(plan["algorithms_requested"], ["cubic", "reno", "bbr"])
        self.assertEqual(Path(plan["server_list_file"]).name, "listed_iperf3_servers.csv")


if __name__ == "__main__":
    unittest.main()
