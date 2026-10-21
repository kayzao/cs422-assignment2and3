from contextlib import contextmanager
import socket
import threading
from types import SimpleNamespace
import time
import unittest
from unittest.mock import patch

from netlab import protocol as wire
from netlab.transfer import TransferError, run_transfer
from netlab.validation import PAYLOAD_BLOCK_SIZE


class TrackedSocket:
    def __init__(self, *args):
        self.raw = socket.socket(*args)
        self.sent = 0
        self.limit = 37 + 2 * PAYLOAD_BLOCK_SIZE + 123

    def __getattr__(self, name):
        return getattr(self.raw, name)

    def sendall(self, value):
        self.raw.sendall(value)
        self.sent += len(value)

    def send(self, value):
        remaining = self.limit - self.sent
        if remaining <= 0:
            raise BlockingIOError()
        count = self.raw.send(value[:min(remaining, 4093)])
        self.sent += count
        return count


@contextmanager
def receiver(mode="exact", delay=0):
    """Synthetic protocol peer that must see data EOF before returning results."""
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen(2)
    listener.settimeout(2)
    observed = {}
    stop = threading.Event()

    def serve():
        try:
            with listener.accept()[0] as control:
                deadline = time.monotonic() + 3
                cookie = wire.recv_exact(control, 37, deadline)
                wire.send_state(control, wire.PARAM_EXCHANGE, deadline, lambda event: None)
                wire.recv_json(control, deadline)
                wire.send_state(control, wire.CREATE_STREAMS, deadline, lambda event: None)
                with listener.accept()[0] as data:
                    data.settimeout(2)
                    self_cookie = wire.recv_exact(data, 37, deadline)
                    if self_cookie != cookie:
                        raise AssertionError("cookie mismatch")
                    wire.send_state(control, wire.TEST_START, deadline, lambda event: None)
                    wire.send_state(control, wire.TEST_RUNNING, deadline, lambda event: None)
                    received = 0
                    while True:
                        chunk = data.recv(PAYLOAD_BLOCK_SIZE)
                        if not chunk:
                            break
                        received += len(chunk)
                    observed.update(eof=True, received=received)
                    if wire.read_state(control, deadline, lambda event: None) != wire.TEST_END:
                        raise AssertionError("missing test end")
                    if stop.wait(delay):
                        return
                    wire.send_state(control, wire.EXCHANGE_RESULTS, deadline, lambda event: None)
                    client = wire.recv_json(control, deadline)
                    observed["client_bytes"] = client["streams"][0]["bytes"]
                    count = received
                    if mode == "partial":
                        count = received // PAYLOAD_BLOCK_SIZE * PAYLOAD_BLOCK_SIZE
                    elif mode == "mismatch":
                        count = received - 1
                    wire.send_json(control, {"streams": [{"id": 1, "bytes": count}]}, deadline)
                    wire.send_state(control, wire.DISPLAY_RESULTS, deadline, lambda event: None)
                    observed["done"] = wire.read_state(control, deadline, lambda event: None) == wire.IPERF_DONE
        except (OSError, RuntimeError, AssertionError, TypeError) as error:
            observed["error"] = str(error)

    thread = threading.Thread(target=serve, daemon=True)
    thread.start()
    try:
        yield listener.getsockname()[1], observed
    finally:
        stop.set()
        listener.close()
        thread.join(timeout=3)
        if thread.is_alive():
            raise AssertionError("synthetic receiver did not stop")


class TransferTests(unittest.TestCase):
    def transfer(self, port, result_timeout=0.8, stalled=False):
        rows, events = [], []

        def reader(sock):
            acked = min(sock.sent, 37) if stalled else sock.sent
            return {"bytes_acked_total": 1 + acked, "total_retrans_segments": 0,
                    "tcp_info_length": 168, "rtt_us": 1000, "rttvar_us": 100,
                    "snd_cwnd_segments": 10, "snd_mss_bytes": 1448,
                    "pacing_rate_Bps": None, "delivery_rate_Bps": None,
                    "unacked_segments": 7 if stalled else 0,
                    "notsent_bytes": 123 if stalled else 0}

        run = {"experiment_id": "synthetic-transfer", "run_id": "run-0001",
               "destination_host": "127.0.0.1", "destination_port": port,
               "algorithm_requested": "synthetic", "repetition": 1}
        module = SimpleNamespace(socket=TrackedSocket, SOCK_STREAM=socket.SOCK_STREAM,
                                 SHUT_WR=socket.SHUT_WR)
        with patch("netlab.transfer.socket", module):
            result = run_transfer(run, 0.08, 0.02, 0.1, 0.04, 1, rows.append, events.append,
                                  reader=reader, algorithm_selector=lambda sock, name: name,
                                  algorithm_reader=lambda sock: "synthetic",
                                  result_timeout_s=result_timeout)
        return result, rows, events

    def test_eof_unblocks_receiver_and_final_results_have_their_own_timeout(self):
        with receiver(delay=0.2) as (port, observed):
            result, rows, events = self.transfer(port)
        self.assertNotIn("error", observed)
        self.assertTrue(observed["eof"])
        self.assertTrue(observed["done"])
        self.assertEqual(observed["received"], 2 * PAYLOAD_BLOCK_SIZE + 123)
        self.assertEqual(observed["received"], observed["client_bytes"])
        self.assertEqual(result["server_byte_count_check"]["status"], "exact")
        self.assertTrue(result["data_write_shutdown"])
        self.assertEqual(result["pending_payload_bytes"], 0)
        self.assertEqual(result["result_exchange_step"], "complete")
        self.assertEqual(sum(row["bytes_acked_delta"] for row in rows), observed["received"])
        names = [event.get("event") for event in events]
        self.assertLess(names.index("payload_write_shutdown"), names.index("server_byte_count_checked"))

    def test_final_partial_block_is_warned_and_protocol_still_completes(self):
        with receiver(mode="partial") as (port, observed):
            result, rows, events = self.transfer(port)
        self.assertNotIn("error", observed)
        self.assertTrue(result["protocol_complete"])
        self.assertEqual(result["server_byte_count_check"]["status"], "partial_block")
        self.assertEqual(result["server_byte_count_check"]["missing_bytes"], 123)
        self.assertEqual(len(result["warnings"]), 1)
        self.assertFalse(result["server_byte_count_matches_sender"])

    def test_receiver_mismatch_is_warned_and_protocol_still_completes(self):
        with receiver(mode="mismatch") as (port, observed):
            result, rows, events = self.transfer(port)
        self.assertTrue(observed["done"])
        self.assertTrue(result["protocol_complete"])
        self.assertEqual(result["server_byte_count_check"]["status"], "mismatch")
        self.assertEqual(result["server_byte_count_check"]["missing_bytes"], 1)
        self.assertEqual(len(result["warnings"]), 1)
        self.assertEqual(result["server_payload_bytes_received"], observed["received"] - 1)

    def test_result_timeout_preserves_exact_step_and_fully_acked_payload(self):
        with receiver(delay=0.3) as (port, observed):
            with self.assertRaises(TransferError) as raised:
                self.transfer(port, result_timeout=0.04)
        error = raised.exception
        self.assertEqual(error.stage, "result_exchange")
        self.assertEqual(error.result["result_exchange_step"], "waiting_for_exchange_results")
        self.assertEqual(error.result["pending_payload_bytes"], 0)
        self.assertEqual(error.result["payload_bytes_sent"], error.result["payload_bytes_acked"])

    def test_drain_timeout_preserves_unsent_unacked_and_elapsed_progress(self):
        with receiver() as (port, observed):
            with self.assertRaises(TransferError) as raised:
                self.transfer(port, stalled=True)
        error = raised.exception
        self.assertEqual(error.stage, "payload_drain")
        self.assertEqual(error.result["payload_bytes_acked"], 0)
        self.assertEqual(error.result["pending_payload_bytes"], 2 * PAYLOAD_BLOCK_SIZE + 123)
        self.assertEqual(error.result["last_payload_snapshot"]["notsent_bytes"], 123)
        self.assertEqual(error.result["last_payload_snapshot"]["unacked_segments"], 7)
        self.assertGreater(error.result["drain_duration_s"], 0)


if __name__ == "__main__":
    unittest.main()
