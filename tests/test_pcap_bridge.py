import io
import socket
import struct
import time
import unittest

from a2qlinux import pcap_bridge
from a2qlinux.pcap_bridge import BridgeServer, read_records

GLOBAL = struct.pack("<IHHiIII", 0xA1B2C3D4, 2, 4, 0, 0, 262144, 1)
GLOBAL_RAW = struct.pack("<IHHiIII", 0xA1B2C3D4, 2, 4, 0, 0, 262144, 101)     # a WireGuard VPN: raw IP


def record(n, payload=b"x" * 10):
    return struct.pack("<IIII", 1000 + n, 0, len(payload), len(payload)) + payload


def request(server, words, token=None, prefix=b"QLPB2 "):
    s = socket.create_connection((server.host, server.port), timeout=5)
    s.sendall(prefix + (token or server.token).encode() + b" " + words.encode() + b"\n")
    return s


def connect(server, interface="eth0", token=None):
    """Open an interface as the DLL does; returns the socket after the OK line."""
    s = request(server, f"open {interface}", token)
    reply = recv_line(s)
    if reply != b"OK":
        raise AssertionError(f"open {interface}: {reply!r}")
    return s


def recv_line(s):
    line = b""
    while not line.endswith(b"\n"):
        chunk = s.recv(1)
        if not chunk:
            return line
        line += chunk
    return line[:-1]


def recv_all(s):
    data = b""
    while True:
        chunk = s.recv(4096)
        if not chunk:
            return data
        data += chunk


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
        self.server.add_interface("eth0", "192.168.1.5")
        self.server.publish("eth0", GLOBAL, None)

    def tearDown(self):
        self.server.stop()

    def test_right_token_gets_header_and_records(self):
        s = connect(self.server)
        self.assertEqual(recv_exact(s, 24), GLOBAL)
        self.assertTrue(wait_for(lambda: self.server.client_count() == 1))
        self.server.publish("eth0", None, record(1))
        self.assertEqual(recv_exact(s, len(record(1))), record(1))
        s.close()

    def test_list_names_every_interface_with_its_address(self):
        self.server.add_interface("proton0", "10.2.0.2")
        self.assertEqual(recv_all(request(self.server, "list")), b"eth0 192.168.1.5\nproton0 10.2.0.2\n\n")
        self.server.remove_interface("eth0")
        self.assertEqual(recv_all(request(self.server, "list")), b"proton0 10.2.0.2\n\n")

    def test_each_interface_gets_its_own_header_and_packets(self):
        self.server.add_interface("proton0", "10.2.0.2")
        self.server.publish("proton0", GLOBAL_RAW, None)
        eth, vpn = connect(self.server, "eth0"), connect(self.server, "proton0")
        self.assertEqual(recv_exact(eth, 24), GLOBAL)
        self.assertEqual(recv_exact(vpn, 24), GLOBAL_RAW)
        self.assertTrue(wait_for(lambda: self.server.client_count() == 2))
        self.server.publish("proton0", None, record(9))
        self.server.publish("eth0", None, record(1))
        self.assertEqual(recv_exact(vpn, len(record(9))), record(9))
        self.assertEqual(recv_exact(eth, len(record(1))), record(1))

    def test_unknown_interface_gets_a_reason_and_is_logged(self):
        s = request(self.server, "open wlan0")
        reply = recv_line(s)
        self.assertTrue(reply.startswith(b"ERR "), reply)
        self.assertIn(b"wlan0", reply)
        self.assertIn(b"eth0", reply)          # what is captured instead
        self.assertTrue(any("wlan0" in m for m in self.messages))

    def test_removing_an_interface_disconnects_its_clients(self):
        s = connect(self.server)
        recv_exact(s, 24)
        self.assertTrue(wait_for(lambda: self.server.client_count() == 1))
        self.server.remove_interface("eth0")
        self.assertEqual(recv_all(s), b"")
        self.assertEqual(self.server.client_count(), 0)

    def test_older_dll_is_refused_with_its_reason(self):
        s = request(self.server, "", prefix=b"QLPB1 ")
        self.assertEqual(recv_all(s), b"")
        self.assertTrue(wait_for(lambda: any("older A2Qlinux wpcap.dll" in m for m in self.messages)))

    def test_followed_interface_is_logged_when_it_changes(self):
        self.server.add_interface("proton0", "10.2.0.2")
        self.server.publish("proton0", GLOBAL_RAW, None)
        for n, name in enumerate(("eth0", "eth0", "proton0", "proton0", "eth0"), 1):
            s = connect(self.server, name)
            recv_exact(s, 24)
            s.close()
            self.assertTrue(wait_for(lambda: self.server.connections == n))
        follows = [m for m in self.messages if "follows" in m]
        self.assertEqual(follows, ["Questlog follows the game's connection on eth0 (192.168.1.5).",
                                   "Questlog follows the game's connection on proton0 (10.2.0.2).",
                                   "Questlog follows the game's connection on eth0 (192.168.1.5)."])

    def test_reconnects_on_the_same_interface_are_logged_once(self):
        # Questlog reconnects on every zone change; one line, not one per zone.
        first = connect(self.server)
        recv_exact(first, 24)
        self.assertTrue(wait_for(lambda: self.server.client_count() == 1))
        first.close()
        for _ in range(3):
            s = connect(self.server)
            recv_exact(s, 24)
            s.close()
        self.assertTrue(wait_for(lambda: self.server.connections == 4))
        follows = [m for m in self.messages if "follows" in m]
        self.assertEqual(follows, ["Questlog follows the game's connection on eth0 (192.168.1.5)."])

    def test_wrong_token_is_refused_and_logged(self):
        s = request(self.server, "open eth0", token="0" * 64)
        self.assertEqual(recv_exact(s, 24), b"")
        self.assertTrue(wait_for(lambda: any("without the right token" in m for m in self.messages)))
        self.assertEqual(self.server.client_count(), 0)

    def test_two_clients_both_get_every_record(self):
        a, b = connect(self.server), connect(self.server)
        recv_exact(a, 24), recv_exact(b, 24)
        self.assertTrue(wait_for(lambda: self.server.client_count() == 2))
        for n in range(3):
            self.server.publish("eth0", None, record(n))
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
                self.server.publish("eth0", None, big)
                got += len(recv_exact(live, len(big)))
                if self.server.client_count() == 1:
                    break
            self.assertEqual(self.server.client_count(), 1)
            self.assertTrue(any("stopped reading" in m for m in self.messages))
            self.server.publish("eth0", None, record(7))
            self.assertEqual(recv_exact(live, len(record(7))), record(7))
        finally:
            pcap_bridge.CLIENT_QUEUE_RECORDS = old


if __name__ == "__main__":
    unittest.main()
