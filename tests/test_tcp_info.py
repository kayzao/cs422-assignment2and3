
import struct
import unittest

from netlab.tcp_info import decode_tcp_info


class TcpInfoTests(unittest.TestCase):


    def test_known_linux_prefix_and_optional_fields(self):


        raw = bytearray(168)
        struct.pack_into("=I", raw, 16, 1448)
        struct.pack_into("=I", raw, 68, 12345)
        struct.pack_into("=I", raw, 72, 234)
        struct.pack_into("=I", raw, 80, 37)
        struct.pack_into("=I", raw, 100, 12)
        struct.pack_into("=Q", raw, 104, 2**64 - 1)
        struct.pack_into("=Q", raw, 120, 2**40 + 123)
        struct.pack_into("=Q", raw, 160, 987654)

        decoded = decode_tcp_info(bytes(raw))
        self.assertEqual(decoded["snd_mss_bytes"], 1448)
        self.assertEqual(decoded["rtt_us"], 12345)
        self.assertEqual(decoded["snd_cwnd_segments"], 37)
        self.assertEqual(decoded["total_retrans_segments"], 12)
        self.assertEqual(decoded["bytes_acked_total"], 2**40 + 123)
        self.assertEqual(decoded["delivery_rate_Bps"], 987654)
        self.assertIsNone(decoded["pacing_rate_Bps"])



    def test_short_kernel_buffer_fails_or_marks_optional_fields_missing(self):

        with self.assertRaisesRegex(RuntimeError, "bytes_acked_total"):
            decode_tcp_info(bytes(127))

        decoded = decode_tcp_info(bytes(128))
        self.assertIsNone(decoded["delivery_rate_Bps"])
        self.assertIsNone(decoded["notsent_bytes"])


if __name__ == "__main__":
    unittest.main()
