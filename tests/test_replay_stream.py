import io
import json
import struct
import unittest

from tools.replay_stream import HOLE_MS, Direction, ReplayWriter, Segment, read_pcap

CLIENT, SERVER = "10.0.0.2", "1.2.3.4"


def collect(direction, pieces):
    """Push (ms, seq, bytes) pieces; return the delivered stream with gaps as '|'."""
    out = []
    for ms, seq, data in pieces:
        direction.push(ms, seq, data, out.append, lambda: out.append(b"|"))
    return b"".join(out)


class DirectionTest(unittest.TestCase):
    def test_in_order(self):
        self.assertEqual(collect(Direction(), [(0, 100, b"ab"), (1, 102, b"cd")]), b"abcd")

    def test_out_of_order_is_held_until_the_hole_fills(self):
        self.assertEqual(collect(Direction(), [(0, 100, b"ab"), (1, 104, b"ef"), (2, 102, b"cd")]), b"abcdef")

    def test_retransmission_is_dropped(self):
        self.assertEqual(collect(Direction(), [(0, 100, b"ab"), (1, 100, b"ab"), (2, 102, b"c")]), b"abc")

    def test_overlap_delivers_only_new_bytes(self):
        self.assertEqual(collect(Direction(), [(0, 100, b"abc"), (1, 101, b"bcde")]), b"abcde")

    def test_hole_older_than_limit_becomes_gap(self):
        got = collect(Direction(), [(0, 100, b"ab"), (10, 110, b"xy"), (10 + HOLE_MS, 112, b"z")])
        self.assertEqual(got, b"ab|xyz")

    def test_hole_younger_than_limit_waits(self):
        got = collect(Direction(), [(0, 100, b"ab"), (10, 110, b"xy"), (HOLE_MS - 1, 112, b"z")])
        self.assertEqual(got, b"ab")

    def test_sequence_wraps_past_2_32(self):
        start = (1 << 32) - 2
        self.assertEqual(collect(Direction(), [(0, start, b"ab"), (1, 0, b"cd"), (2, 2, b"e")]), b"abcde")

    def test_syn_sets_the_start(self):
        d = Direction()
        d.start_after_syn(99)
        self.assertEqual(collect(d, [(0, 102, b"cd"), (1, 100, b"ab")]), b"abcd")


def seg(ms, out, seq, payload=b"", syn=False, fin=False, port=50000):
    if out:
        return Segment(ms, CLIENT, port, SERVER, 13328, seq, syn, fin, False, payload)
    return Segment(ms, SERVER, 13328, CLIENT, port, seq, syn, fin, False, payload)


def lines(buffer):
    return [json.loads(line) for line in buffer.getvalue().splitlines()]


class ReplayWriterTest(unittest.TestCase):
    def test_full_connection(self):
        buf = io.StringIO()
        w = ReplayWriter(buf)
        w.feed(seg(1, True, 10, syn=True))
        w.feed(seg(2, False, 500, syn=True))
        w.feed(seg(3, True, 11, b"hi"))
        w.feed(seg(4, False, 501, b"yo"))
        w.feed(seg(5, True, 13, fin=True))
        conn = f"{CLIENT}:50000-{SERVER}:13328"
        self.assertEqual(lines(buf), [
            [1, "open", conn, f"{CLIENT}:50000", f"{SERVER}:13328"],
            [3, "data", conn, "out", "aGk="],
            [4, "data", conn, "in", "eW8="],
            [5, "close", conn],
        ])

    def test_mid_stream_connection_has_no_open(self):
        buf = io.StringIO()
        w = ReplayWriter(buf)
        w.feed(seg(1, False, 700, b"x"))
        self.assertEqual([row[1] for row in lines(buf)], ["data"])

    def test_timestamps_never_go_back(self):
        buf = io.StringIO()
        w = ReplayWriter(buf)
        w.feed(seg(100, False, 700, b"a"))
        w.tick(150)
        w.feed(seg(120, False, 701, b"b"))
        self.assertEqual([row[0] for row in lines(buf)], [100, 150, 150])

    def test_no_tick_before_the_first_event(self):
        buf = io.StringIO()
        w = ReplayWriter(buf)
        w.tick(1)
        w.feed(seg(2, False, 700, b"a"))
        w.tick(3)
        conn = f"{CLIENT}:50000-{SERVER}:13328"
        self.assertEqual(lines(buf)[0][1], "data")
        self.assertEqual(lines(buf)[1], [3, "tick", conn])

    def test_ticks_continue_after_the_connection_closes(self):
        buf = io.StringIO()
        w = ReplayWriter(buf)
        w.feed(seg(1, False, 700, b"a"))
        w.feed(seg(2, True, 10, fin=True))
        w.tick(3)
        self.assertEqual(lines(buf)[-1][1], "tick")

    def test_gaps_are_counted(self):
        buf = io.StringIO()
        w = ReplayWriter(buf)
        w.feed(seg(0, False, 700, b"a"))
        w.feed(seg(10, False, 710, b"b"))
        w.feed(seg(10 + HOLE_MS, False, 711, b"c"))
        self.assertEqual(w.gaps, 1)
        self.assertIn("gap", [row[1] for row in lines(buf)])

    def test_other_ports_are_ignored(self):
        buf = io.StringIO()
        w = ReplayWriter(buf)
        w.feed(Segment(1, CLIENT, 1, SERVER, 443, 1, False, False, False, b"x"))
        self.assertEqual(buf.getvalue(), "")


def pcap_bytes(frames, linktype=1):
    out = struct.pack("<IHHiIII", 0xA1B2C3D4, 2, 4, 0, 0, 65535, linktype)
    for usec, frame in frames:
        out += struct.pack("<IIII", usec // 1_000_000, usec % 1_000_000, len(frame), len(frame)) + frame
    return out


def ethernet_tcp(src, dst, sport, dport, seq, flags, payload):
    tcp = struct.pack("!HHIIBBHHH", sport, dport, seq, 0, 5 << 4, flags, 65535, 0, 0) + payload
    ip = struct.pack("!BBHHHBBH4s4s", 0x45, 0, 20 + len(tcp), 0, 0x4000, 64, 6, 0,
                     bytes(map(int, src.split("."))), bytes(map(int, dst.split(".")))) + tcp
    return b"\0" * 12 + b"\x08\x00" + ip


class ReadPcapTest(unittest.TestCase):
    def test_reads_tcp_segment(self):
        frame = ethernet_tcp(SERVER, CLIENT, 13328, 50000, 7, 0x18, b"data")
        (s,) = list(read_pcap(io.BytesIO(pcap_bytes([(1_500_000, frame)]))))
        self.assertEqual((s.ms, s.src, s.sport, s.dst, s.dport, s.seq, s.payload),
                         (1500, SERVER, 13328, CLIENT, 50000, 7, b"data"))
        self.assertFalse(s.syn or s.fin or s.rst)

    def test_rejects_pcapng(self):
        with self.assertRaises(ValueError):
            list(read_pcap(io.BytesIO(b"\x0a\x0d\x0d\x0a" + b"\0" * 40)))

    def test_rejects_unknown_link_type(self):
        with self.assertRaises(ValueError):
            list(read_pcap(io.BytesIO(pcap_bytes([], linktype=105))))

    def test_truncated_packet_is_an_error(self):
        frame = ethernet_tcp(SERVER, CLIENT, 13328, 50000, 7, 0x18, b"data")
        data = pcap_bytes([(0, frame)])[:-3]
        with self.assertRaises(ValueError):
            list(read_pcap(io.BytesIO(data)))


if __name__ == "__main__":
    unittest.main()
