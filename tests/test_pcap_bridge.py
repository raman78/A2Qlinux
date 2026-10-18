import io
import socket
import struct
import time
import unittest

import pcap_bridge
from pcap_bridge import BridgeServer, read_records

GLOBAL = struct.pack("<IHHiIII", 0xA1B2C3D4, 2, 4, 0, 0, 262144, 1)


def record(n, payload=b"x" * 10):
    return struct.pack("<IIII", 1000 + n, 0, len(payload), len(payload)) + payload


def connect(server, token=None):
    s = socket.create_connection((server.host, server.port), timeout=5)
    s.sendall(b"QLPB1 " + (token or server.token).encode() + b"\n")
    return s


def recv_exact(s, n):
    data = b""
    while len(data) < n:
        chunk = s.recv(n - len(data))
        if not chunk:
            return data
        data += chunk
    return data


def wait_for(cond, timeout=3):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if cond():
            return True
        time.sleep(0.01)
    return False


class ReadRecordsTest(unittest.TestCase):
    def test_header_then_records(self):
        items = list(read_records(io.BytesIO(GLOBAL + record(1) + record(2))))
        self.assertEqual(items[0], (GLOBAL, None))
        self.assertEqual([r for _, r in items[1:]], [record(1), record(2)])

    def test_nanosecond_stamps_become_microseconds(self):
        nano_global = b"\x4d\x3c\xb2\xa1" + GLOBAL[4:]
        nano_record = struct.pack("<IIII", 5, 123456789, 3, 3) + b"abc"
        items = list(read_records(io.BytesIO(nano_global + nano_record)))
        self.assertEqual(items[0][0], GLOBAL)
        self.assertEqual(items[1][1], struct.pack("<IIII", 5, 123456, 3, 3) + b"abc")

    def test_rejects_pcapng(self):
        with self.assertRaises(ValueError):
            list(read_records(io.BytesIO(b"\x0a\x0d\x0d\x0a" + b"\0" * 40)))

    def test_truncated_record_is_an_error(self):
        with self.assertRaises(ValueError):
            list(read_records(io.BytesIO(GLOBAL + record(1)[:-2])))


class BridgeServerTest(unittest.TestCase):
    def setUp(self):
        self.messages = []
        self.server = BridgeServer(self.messages.append)
        self.server.publish(GLOBAL, None)

    def tearDown(self):
        self.server.stop()

    def test_right_token_gets_header_and_records(self):
        s = connect(self.server)
        self.assertEqual(recv_exact(s, 24), GLOBAL)
        self.assertTrue(wait_for(lambda: self.server.client_count() == 1))
        self.server.publish(None, record(1))
        self.assertEqual(recv_exact(s, len(record(1))), record(1))
        s.close()

    def test_wrong_token_is_refused_and_logged(self):
        s = connect(self.server, token="0" * 64)
        self.assertEqual(recv_exact(s, 24), b"")
        self.assertTrue(wait_for(lambda: any("without the right token" in m for m in self.messages)))
        self.assertEqual(self.server.client_count(), 0)

    def test_two_clients_both_get_every_record(self):
        a, b = connect(self.server), connect(self.server)
        recv_exact(a, 24), recv_exact(b, 24)
        self.assertTrue(wait_for(lambda: self.server.client_count() == 2))
        for n in range(3):
            self.server.publish(None, record(n))
        expected = b"".join(record(n) for n in range(3))
        self.assertEqual(recv_exact(a, len(expected)), expected)
        self.assertEqual(recv_exact(b, len(expected)), expected)

    def test_client_that_stops_reading_is_dropped_others_keep_going(self):
        old = pcap_bridge.CLIENT_QUEUE_RECORDS
        pcap_bridge.CLIENT_QUEUE_RECORDS = 5
        try:
            stuck, live = connect(self.server), connect(self.server)
            recv_exact(stuck, 24), recv_exact(live, 24)
            self.assertTrue(wait_for(lambda: self.server.client_count() == 2))
            big = record(0, b"y" * 200000)            # fills the stuck client's socket buffers fast
            got = 0
            for n in range(200):
                self.server.publish(None, big)
                got += len(recv_exact(live, len(big)))
                if self.server.client_count() == 1:
                    break
            self.assertEqual(self.server.client_count(), 1)
            self.assertTrue(any("stopped reading" in m for m in self.messages))
            self.server.publish(None, record(7))
            self.assertEqual(recv_exact(live, len(record(7))), record(7))
        finally:
            pcap_bridge.CLIENT_QUEUE_RECORDS = old


if __name__ == "__main__":
    unittest.main()
