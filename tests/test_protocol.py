
import json
import socket
import struct
import threading
import time
import unittest

from netlab import protocol as wire


class ProtocolTests(unittest.TestCase):


    def test_fragmented_frame_and_coalesced_next_state(self):

        left, right = socket.socketpair()
        body = json.dumps({"streams": [{"id": 1, "bytes": 123}]}).encode()
        frame = struct.pack("!I", len(body)) + body + bytes([wire.DISPLAY_RESULTS])
        errors = []



        def send_fragments():
            try:
                for offset in range(0, len(frame), 2):
                    right.sendall(frame[offset:offset + 2])
                    time.sleep(0.001)
            except Exception as error:
                errors.append(error)
            finally:
                right.close()


        worker = threading.Thread(target=send_fragments)
        worker.start()
        try:
            deadline = time.monotonic() + 2
            self.assertEqual(wire.recv_json(left, deadline)["streams"][0]["bytes"], 123)
            wire.expect_state(left, wire.DISPLAY_RESULTS, deadline, lambda row: None)
        finally:
            left.close()
            worker.join(timeout=3)
        self.assertFalse(worker.is_alive())
        self.assertFalse(errors)



    def test_rejects_truncated_and_oversized_json(self):

        for content in (struct.pack("!I", 99) + b"{}",
                        struct.pack("!I", wire.MAX_JSON_BYTES + 1),
                        struct.pack("!I", 3) + b"[] ",
                        struct.pack("!I", 9) + b'{"a":NaN}',
                        struct.pack("!I", 11) + b'{"a":1e999}'):
            with self.subTest(content=content), self._pair(content) as left:
                with self.assertRaises(wire.ProtocolError):
                    wire.recv_json(left, time.monotonic() + 1)



    @staticmethod
    def _pair(content):
        left, right = socket.socketpair()
        right.sendall(content)
        right.close()
        return left



    def test_signed_rejection_and_server_error(self):

        for content, message in ((b"\xff", "denied"),
                                 (b"\xfe" + struct.pack("!ii", 123, 13), "iperf_code=123")):
            with self._pair(content) as left:
                with self.assertRaisesRegex(wire.ProtocolError, message):
                    wire.read_state(left, time.monotonic() + 1, lambda row: None)



    def test_read_has_an_absolute_deadline(self):
        with self._idle_pair() as left:
            start = time.monotonic()
            with self.assertRaises((TimeoutError, socket.timeout)):
                wire.recv_exact(left, 4, start + 0.03)
            self.assertLess(time.monotonic() - start, 0.5)



    def _idle_pair(self):
        left, right = socket.socketpair()
        self.addCleanup(right.close)
        return left



if __name__ == "__main__":
    unittest.main()
