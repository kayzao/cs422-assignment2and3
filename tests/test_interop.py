"""Optional protocol-only check against an official local iperf3 SERVER.

No iperf3 client is invoked. Injected counters are synthetic: this check proves
wire interoperability, not Linux statistics accuracy or assignment measurements.
Set IPERF3_SERVER_BINARY to an installed/built official binary to enable it.
"""


import os
from pathlib import Path
import socket
import subprocess
import time
import unittest

from netlab.transfer import run_transfer



@unittest.skipUnless(os.environ.get("IPERF3_SERVER_BINARY"), "optional standard-server interoperability check")
class StandardServerTests(unittest.TestCase):


    def test_complete_upload_and_results_with_standard_server(self):
        binary = Path(os.environ["IPERF3_SERVER_BINARY"]).resolve()

        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            port = probe.getsockname()[1]

        server = subprocess.Popen([str(binary), "-s", "-1", "-B", "127.0.0.1", "-p", str(port)],
                                  stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)

        rows, events = [], []
        ticks = 0



        def synthetic_reader(sock):
            nonlocal ticks
            ticks += 1
            return {"bytes_acked_total": ticks * 10**12, "total_retrans_segments": 0,
                    "tcp_info_length": 168, "rtt_us": 1000, "rttvar_us": 100,
                    "snd_cwnd_segments": 10, "snd_mss_bytes": 1448,
                    "pacing_rate_Bps": None, "delivery_rate_Bps": None,
                    "unacked_segments": 0, "notsent_bytes": 0}

        try:


            time.sleep(1)
            if server.poll() is not None:
                stdout, stderr = server.communicate()
                self.fail(f"official server failed to start: {stdout} {stderr}")

            run = {"experiment_id": "synthetic-interop", "run_id": "run-0001",
                   "destination_host": "127.0.0.1", "destination_port": port,
                   "algorithm_requested": "synthetic-test", "repetition": 1}
            result = run_transfer(run, 0.3, 0.2, 3, 1, 0.05, rows.append, events.append,
                                  reader=synthetic_reader,
                                  algorithm_selector=lambda sock, name: name,
                                  algorithm_reader=lambda sock: "synthetic-test")

            self.assertTrue(result["protocol_complete"])
            self.assertGreater(result["server_payload_bytes_received"], 0)
            self.assertEqual(rows[0]["phase"], "baseline")
            self.assertIsNone(rows[0]["goodput_bps"])
            states = [event.get("state") for event in events]
            self.assertIn("EXCHANGE_RESULTS", states)
            self.assertIn("IPERF_DONE", states)
            server.wait(timeout=5)
            self.assertEqual(server.returncode, 0)

        finally:
            if server.poll() is None:
                server.terminate()
            server.communicate(timeout=5)


if __name__ == "__main__":
    unittest.main()
