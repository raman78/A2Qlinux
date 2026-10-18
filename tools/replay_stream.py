"""Turn captured AION 2 packets into Questlog's replay stream (QUESTLOG_REPLAY).

Questlog Desktop reads a replay as one JSON array per line:

    [ms, "open",  conn, local, remote]
    [ms, "data",  conn, "in"|"out", base64]   in-order TCP payload
    [ms, "gap",   conn, "in"|"out"]           bytes were lost, the stream resyncs
    [ms, "close", conn]

`conn` is "<local ip:port>-<remote ip:port>" and "in" is server -> client.
Questlog ignores any other kind on a connection it has already seen; the
"tick" lines written here use that to keep its replay clock current (see
`ReplayWriter.tick`).

This module has two parts: a reader for classic pcap (what `dumpcap -F pcap`
writes) and the TCP reassembly that turns segments into the events above.
"""

import base64
import json
import struct

SERVER_PORT = 13328
HOLE_MS = 1000          # a hole not filled within this long is reported as a gap
SEQ_MOD = 1 << 32

LINKTYPE_ETHERNET = 1
LINKTYPE_LINUX_SLL = 113


class Segment:
    __slots__ = ("ms", "src", "sport", "dst", "dport", "seq", "syn", "fin", "rst", "payload")

    def __init__(self, ms, src, sport, dst, dport, seq, syn, fin, rst, payload):
        self.ms, self.src, self.sport, self.dst, self.dport = ms, src, sport, dst, dport
        self.seq, self.syn, self.fin, self.rst, self.payload = seq, syn, fin, rst, payload


def _read_exact(stream, n):
    data = b""
    while len(data) < n:
        chunk = stream.read(n - len(data))
        if not chunk:
            return None if not data else data
        data += chunk
    return data


def read_pcap(stream):
    """Yield TCP/IPv4 segments from a classic pcap stream (file or pipe).

    Raises ValueError on a stream that is not classic pcap, or uses a link type
    this reader does not know, so a wrong capture setting is never silently
    read as "no packets".
    """
    header = _read_exact(stream, 24)
    if header is None or len(header) < 24:
        raise ValueError("The capture stream ended before its pcap header.")
    magic = header[:4]
    if magic in (b"\xd4\xc3\xb2\xa1", b"\x4d\x3c\xb2\xa1"):
        endian = "<"
    elif magic in (b"\xa1\xb2\xc3\xd4", b"\xa1\xb2\x3c\x4d"):
        endian = ">"
    else:
        raise ValueError("The capture stream is not classic pcap (dumpcap needs -F pcap).")
    nanos = magic in (b"\x4d\x3c\xb2\xa1", b"\xa1\xb2\x3c\x4d")
    linktype = struct.unpack(endian + "I", header[20:24])[0] & 0x0FFFFFFF
    if linktype == LINKTYPE_ETHERNET:
        link_len = 14
    elif linktype == LINKTYPE_LINUX_SLL:
        link_len = 16
    else:
        raise ValueError(f"Unsupported capture link type {linktype}.")
    record = struct.Struct(endian + "IIII")
    while True:
        head = _read_exact(stream, 16)
        if head is None:
            return
        if len(head) < 16:
            raise ValueError("The capture stream ended inside a packet header.")
        sec, frac, caplen, _ = record.unpack(head)
        frame = _read_exact(stream, caplen)
        if frame is None or len(frame) < caplen:
            raise ValueError("The capture stream ended inside a packet.")
        ms = sec * 1000 + (frac // 1_000_000 if nanos else frac // 1000)
        segment = _parse_frame(frame, link_len, ms)
        if segment is not None:
            yield segment


def _parse_frame(frame, link_len, ms):
    ethertype = struct.unpack("!H", frame[link_len - 2:link_len])[0] if len(frame) >= link_len else 0
    offset = link_len
    if ethertype == 0x8100 and len(frame) >= offset + 4:      # one VLAN tag
        ethertype = struct.unpack("!H", frame[offset + 2:offset + 4])[0]
        offset += 4
    if ethertype != 0x0800 or len(frame) < offset + 20:
        return None
    ip = frame[offset:]
    if ip[0] >> 4 != 4 or ip[9] != 6:
        return None
    ihl = (ip[0] & 0x0F) * 4
    total = struct.unpack("!H", ip[2:4])[0]
    flags_frag = struct.unpack("!H", ip[6:8])[0]
    if flags_frag & 0x1FFF or flags_frag & 0x2000:          # IP fragments carry no usable TCP header
        return None
    ip = ip[:total]
    tcp = ip[ihl:]
    if len(tcp) < 20:
        return None
    sport, dport, seq = struct.unpack("!HHI", tcp[:8])
    data_offset = (tcp[12] >> 4) * 4
    flags = tcp[13]
    payload = bytes(tcp[data_offset:])
    src = ".".join(str(b) for b in ip[12:16])
    dst = ".".join(str(b) for b in ip[16:20])
    return Segment(ms, src, sport, dst, dport, seq,
                   bool(flags & 0x02), bool(flags & 0x01), bool(flags & 0x04), payload)


class Direction:
    """In-order reassembly of one direction of one TCP connection.

    Sequence numbers are unwrapped onto an unbounded line, so a stream that
    crosses 2**32 keeps its order. Retransmitted bytes are dropped; a hole
    that stays open for HOLE_MS is given up on and reported as a gap.
    """

    def __init__(self):
        self.next = None
        self.pending = {}        # absolute seq -> (bytes, first seen ms)

    def _unwrap(self, seq):
        if self.next is None:
            return seq
        delta = (seq - self.next + (SEQ_MOD >> 1)) % SEQ_MOD - (SEQ_MOD >> 1)
        return self.next + delta

    def start_after_syn(self, seq):
        self.next = seq + 1
        self.pending.clear()

    def push(self, ms, seq, data, emit_data, emit_gap):
        seq = self._unwrap(seq)
        if self.next is None:
            self.next = seq
        if seq + len(data) <= self.next:
            return
        if seq < self.next:
            data = data[self.next - seq:]
            seq = self.next
        held = self.pending.get(seq)
        if held is None or len(held[0]) < len(data):
            self.pending[seq] = (data, held[1] if held else ms)
        self._drain(ms, emit_data, emit_gap)

    def _drain(self, ms, emit_data, emit_gap):
        while self.pending:
            if self.next in self.pending:
                data, _ = self.pending.pop(self.next)
                emit_data(data)
                self.next += len(data)
                continue
            first = min(self.pending)
            if first < self.next:
                data, seen = self.pending.pop(first)
                if first + len(data) > self.next:
                    rest = data[self.next - first:]
                    held = self.pending.get(self.next)
                    if held is None or len(held[0]) < len(rest):
                        self.pending[self.next] = (rest, seen)
                continue
            if ms - self.pending[first][1] >= HOLE_MS:
                emit_gap()
                self.next = first
                continue
            return


class ReplayWriter:
    """Reassemble segments of the game connections and write replay lines.

    `out` needs only `write(str)`. Timestamps never go backwards: dumpcap hands
    packets over in batches, and a stamp older than the line before it would
    pull Questlog's replay clock back and make the next wait longer.
    """

    def __init__(self, out, server_port=SERVER_PORT):
        self.out = out
        self.server_port = server_port
        self.conns = {}
        self.closed = set()
        self.last_ms = None
        self.tick_conn = None
        self.gaps = 0           # holes given up on; each one may cost Questlog a few events

    def _write(self, ms, *row):
        if self.last_ms is not None and ms < self.last_ms:
            ms = self.last_ms
        self.last_ms = ms
        if self.tick_conn is None and row[0] != "tick":
            # Questlog registers a connection on its first line of any kind.
            self.tick_conn = row[1]
        self.out.write(json.dumps([ms, *row]) + "\n")

    def tick(self, now_ms):
        """Write a line Questlog skips, to keep its replay clock current.

        Questlog's replay sleeps, before each line, for the time since the line
        before it. Fed live, that sleep comes on top of the real wait, so after
        a quiet spell every later event would arrive that much late, for good.
        Lines every few tens of milliseconds keep each sleep that short. A tick
        needs a connection Questlog has already seen, so none is written until
        the first event.
        """
        if self.tick_conn is not None:
            self._write(now_ms, "tick", self.tick_conn)

    def _gap(self, ms, conn, direction):
        self.gaps += 1
        self._write(ms, "gap", conn, direction)

    def feed(self, s):
        if s.dport == self.server_port:
            local, remote, direction = f"{s.src}:{s.sport}", f"{s.dst}:{s.dport}", "out"
        elif s.sport == self.server_port:
            local, remote, direction = f"{s.dst}:{s.dport}", f"{s.src}:{s.sport}", "in"
        else:
            return
        conn = f"{local}-{remote}"
        if conn in self.closed:
            return
        state = self.conns.get(conn)
        if state is None:
            state = self.conns[conn] = {"in": Direction(), "out": Direction()}
            if s.syn:
                self._write(s.ms, "open", conn, local, remote)
        d = state[direction]
        if s.syn:
            d.start_after_syn(s.seq)
            return
        if s.payload:
            d.push(s.ms, s.seq, s.payload,
                   lambda b: self._write(s.ms, "data", conn, direction, base64.b64encode(b).decode()),
                   lambda: self._gap(s.ms, conn, direction))
        if s.fin or s.rst:
            self._write(s.ms, "close", conn)
            del self.conns[conn]
            self.closed.add(conn)
