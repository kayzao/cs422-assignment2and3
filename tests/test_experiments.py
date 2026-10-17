from pathlib import Path
import tempfile
import unittest

from netlab.experiments import Server, build_plan, load_servers


class ExperimentTests(unittest.TestCase):
    def load_csv(self, content):
        # Temporary fixtures test CSV parsing without public-server dependencies.
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "servers.csv"
            path.write_text(content)
            return load_servers(path)

    def test_csv_trims_hosts_deduplicates_and_accepts_ipv6(self):
        # Duplicate endpoints should not get extra chances in A2 Q1(b)'s draw.
        self.assertEqual(
            self.load_csv("host,port\n A.example ,5201\na.example,5201\n2001:db8::1,5202\n"),
            [Server("A.example", 5201), Server("2001:db8::1", 5202)],
        )

    def test_invalid_csv_is_rejected(self):
        for content in (
            "address,port\na.example,5201\n", "host,port\na.example,0\n",
            "host,port\na.example,65536\n", "host,port\n,5201\n",
            "host,port\nhttps://a.example,5201\n", "host,port\n",
        ):
            with self.subTest(content=content), self.assertRaises(ValueError):
                self.load_csv(content)

    def plan(self, **overrides):
        # Shared test settings; overrides exercise one invalid setting at a time.
        arguments = dict(
            destinations=2, algorithms=["cubic", "reno", "bbr"],
            duration_s=10, interval_s=0.2, repetitions=3, seed=422,
        )
        arguments.update(overrides)
        return build_plan([Server(f"s{i}.example", 5201) for i in range(5)], **arguments)

    def test_reproducible_matched_schedule_and_rotating_order(self):
        # A2 Q3(a): same selected endpoints for each algorithm, repeated runs,
        # and a recorded order that does not always put the same algorithm first.
        result = self.plan()
        self.assertEqual(result, self.plan())
        # 2 destinations * 3 algorithms * 3 repetitions = 18 planned transfers.
        self.assertEqual(len(result["runs"]), 18)
        self.assertEqual(result["active_transfer_seconds"], 180)
        selected = {s["host"] for s in result["selected_destinations"]}
        self.assertEqual({r["destination_host"] for r in result["runs"]}, selected)
        for host in selected:
            first_positions = []
            for repetition in range(1, 4):
                algorithms = [r["algorithm_requested"] for r in result["runs"]
                              if r["destination_host"] == host and r["repetition"] == repetition]
                self.assertEqual(set(algorithms), {"cubic", "reno", "bbr"})
                first_positions.append(algorithms[0])
            self.assertEqual(len(set(first_positions)), 3)

    def test_custom_algorithm_and_invalid_configuration(self):
        # A3 Option 1 can later schedule a registered custom controller by name;
        # accepting its label here does not verify that a Linux kernel supports it.
        self.assertEqual(self.plan(algorithms=["my_controller"])["algorithms_requested"], ["my_controller"])
        for overrides in (
            {"destinations": 0}, {"destinations": 6}, {"repetitions": 0},
            {"duration_s": float("nan")}, {"interval_s": 11},
            {"algorithms": []}, {"algorithms": ["cubic", "cubic"]},
        ):
            with self.subTest(overrides=overrides), self.assertRaises(ValueError):
                self.plan(**overrides)


if __name__ == "__main__":
    unittest.main()
