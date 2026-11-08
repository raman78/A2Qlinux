"""Serve captured packets to the wpcap.dll stand-in inside Proton.

The launcher captures on every usable network interface (one dumpcap each)
and registers each one here as a channel. The DLL (bridge/wpcap_bridge.c)
connects to this server on 127.0.0.1 and sends one request line:

    "QLPB2 <token> list\\n"         -> "<interface> <IPv4>\\n" per channel, then
                                      an empty line; the server closes
    "QLPB2 <token> open <name>\\n"  -> "OK\\n", then that interface's classic pcap
                                      stream: the 24-byte global header,
                                      followed by packet records (16-byte
                                      record header + frame); or
                                      "ERR <reason>\\n" and the server closes

The list is what pcap_findalldevs reports, so Questlog picks the interface
whose address its game connection uses, as it picks an adapter on Windows.
Each pcap_open_live is one "open" connection; Questlog opens a new one when
the game's connections change and only then closes the old, so several
clients can be connected at once and each gets every packet of its channel.

The token keeps other local programs from reading the game traffic (it
carries chat). It reaches the DLL through the QUESTLOG_PROTON_BRIDGE variable
of the Questlog process only.
"""

import hmac
import queue
import secrets
import socket
import struct
import threading

HELLO_PREFIX = b"QLPB2 "
MICROSECOND_MAGIC = b"\xd4\xc3\xb2\xa1"
CLIENT_QUEUE_RECORDS = 5000       # ~2 min of ordinary game traffic, ~10 s of the heaviest; beyond it the client is stuck


def read_records(stream):
    """Yield (global_header, None) once, then (None, record_bytes) per packet.

    Output is always little-endian microsecond pcap. Raises ValueError on
    anything else coming in, so a wrong dumpcap setting is never read as
    "no packets".
    """
    header = _read_exact(stream, 24)
    if header is None or len(header) < 24:
        raise ValueError("The capture stream ended before its pcap header.")
    if header[:4] == b"\xd4\xc3\xb2\xa1":
        nanos = False
    elif header[:4] == b"\x4d\x3c\xb2\xa1":
        nanos = True        # what dumpcap -F pcap writes
    else:
        raise ValueError("The capture stream is not little-endian classic pcap (dumpcap needs -F pcap).")
    # The DLL hands record headers to Questlog as they are, and Questlog reads
    # the second field as microseconds; nanosecond stamps are converted here.
    yield MICROSECOND_MAGIC + header[4:], None
    while True:
        head = _read_exact(stream, 16)
        if head is None:
            return
        if len(head) < 16:
            raise ValueError("The capture stream ended inside a packet header.")
        seconds, fraction, caplen, length = struct.unpack("<IIII", head)
        frame = _read_exact(stream, caplen)
        if frame is None or len(frame) < caplen:
            raise ValueError("The capture stream ended inside a packet.")
        if nanos:
            head = struct.pack("<IIII", seconds, fraction // 1000, caplen, length)
        yield None, head + frame


def _read_exact(stream, n):
    data = b""
    while len(data) < n:
        chunk = stream.read(n - len(data))
        if not chunk:
            return None if not data else data
        data += chunk
    return data


class _Client:
    def __init__(self, sock, peer, global_header, log):
        self.sock = sock
        self.peer = peer
        self.log = log
        self.queue = queue.Queue(maxsize=CLIENT_QUEUE_RECORDS)
        self.closed = threading.Event()
        self.sent = 0
        sock.sendall(global_header)
        threading.Thread(target=self._send_loop, daemon=True).start()

    def offer(self, record):
        """Queue a record; a client that has stopped reading is disconnected."""
        if self.closed.is_set():
            return False
        try:
            self.queue.put_nowait(record)
            return True
        except queue.Full:
            self.log(f"Questlog stopped reading packets ({CLIENT_QUEUE_RECORDS} waiting); "
                     "dropping its connection - it reconnects by itself within a second.")
            self.close()
            return False

    def _send_loop(self):
        try:
            while not self.closed.is_set():
                record = self.queue.get()
                if record is None:
                    break
                self.sock.sendall(record)
                self.sent += 1
        except OSError:
            pass
        finally:
            self.close()

    def close(self):
        if not self.closed.is_set():
            self.closed.set()
            try:
                self.queue.put_nowait(None)
            except queue.Full:
                pass
            try:
                self.sock.close()
            except OSError:
                pass


class _Channel:
    """One captured interface: its address, its pcap header once dumpcap sent it, its clients."""

    def __init__(self, address):
        self.address = address
        self.global_header = None
        self.header_ready = threading.Event()
        self.clients = []


class BridgeServer:
    """Accept authenticated DLL connections and fan each interface's packet records out to them."""

    def __init__(self, log, host="127.0.0.1"):
        self.log = log
        self.token = secrets.token_hex(32)
        self.listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.listener.bind((host, 0))
        self.listener.listen(8)
        self.host, self.port = self.listener.getsockname()
        self.channels = {}
        self.lock = threading.Lock()
        self.connections = 0
        self.followed = None        # (interface, address) of the last device Questlog opened
        self.stopped = threading.Event()
        threading.Thread(target=self._accept_loop, daemon=True).start()

    def environment_value(self):
        """The QUESTLOG_PROTON_BRIDGE value the DLL reads."""
        return f"{self.host}:{self.port}:{self.token}"

    def add_interface(self, name, address):
        """Offer an interface to Questlog; its packets follow through publish()."""
        with self.lock:
            self.channels[name] = _Channel(address)

    def remove_interface(self, name):
        """Withdraw an interface; its clients are disconnected, and Questlog lists the devices again."""
        with self.lock:
            channel = self.channels.pop(name, None)
        if channel:
            for client in channel.clients:
                client.close()

    def _accept_loop(self):
        while not self.stopped.is_set():
            try:
                sock, peer = self.listener.accept()
            except OSError:
                return
            threading.Thread(target=self._admit, args=(sock, peer), daemon=True).start()

    def _request(self, sock, peer):
        """The authenticated request words, or None (refusal logged)."""
        line = b""
        while not line.endswith(b"\n") and len(line) < 300:
            chunk = sock.recv(300 - len(line))
            if not chunk:
                break
            line += chunk
        prefix = HELLO_PREFIX + self.token.encode()
        if not (hmac.compare_digest(line[:len(prefix)], prefix) and line[len(prefix):len(prefix) + 1] == b" "
                and line.endswith(b"\n")):
            what = ("from an older A2Qlinux wpcap.dll (restart Questlog through A2Qlinux)"
                    if line.startswith(b"QLPB1 ") else "without the right token")
            self.log(f"Refused a connection from {peer[0]}:{peer[1]} {what}.")
            return None
        return line[len(prefix) + 1:-1].decode("ascii", "replace").split(" ")

    def _admit(self, sock, peer):
        try:
            sock.settimeout(5)
            words = self._request(sock, peer)
            if words is None:
                sock.close()
                return
            if words == ["list"]:
                with self.lock:
                    listing = "".join(f"{name} {c.address}\n" for name, c in self.channels.items())
                sock.sendall(listing.encode() + b"\n")
                sock.close()
                return
            if len(words) != 2 or words[0] != "open":
                self.log(f"Refused an unknown request from the capture DLL: {' '.join(words)!r}.")
                sock.sendall(b"ERR Unknown request to the capture bridge (A2Qlinux and its wpcap.dll differ)\n")
                sock.close()
                return
            name = words[1]
            with self.lock:
                channel = self.channels.get(name)
                captured = ", ".join(self.channels) or "none"
            if channel is None:
                reason = f"A2Qlinux does not capture on {name} (any more); it captures on: {captured}"
                self.log(f"Questlog asked for {name}, which is not captured; it captures on: {captured}.")
                sock.sendall(f"ERR {reason}\n".encode())
                sock.close()
                return
            if not channel.header_ready.wait(timeout=5):
                self.log(f"Questlog connected before dumpcap started on {name}; it will retry.")
                sock.sendall(f"ERR dumpcap has not started on {name} yet\n".encode())
                sock.close()
                return
            sock.settimeout(None)
            sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            sock.sendall(b"OK\n")
            client = _Client(sock, peer, channel.global_header, self.log)
        except OSError:
            sock.close()
            return
        with self.lock:
            if self.channels.get(name) is not channel:      # withdrawn meanwhile
                client.close()
                return
            channel.clients.append(client)
            self.connections += 1
            followed, self.followed = self.followed, (name, channel.address)
        # Questlog reconnects by design on every zone change (it opens the new
        # device before closing the old one), so a line only when the interface
        # it follows changes; what is abnormal (refused, dropped) is logged above.
        if followed != (name, channel.address):
            self.log(f"Questlog follows the game's connection on {name} ({channel.address}).")

    def publish(self, name, global_header, record):
        """Feed one item from read_records() of interface `name`."""
        with self.lock:
            channel = self.channels.get(name)
            if channel is None:
                return
            if global_header is not None:
                channel.global_header = global_header
                channel.header_ready.set()
                return
            channel.clients = [c for c in channel.clients if c.offer(record)]

    def client_count(self):
        with self.lock:
            count = 0
            for channel in self.channels.values():
                channel.clients = [c for c in channel.clients if not c.closed.is_set()]
                count += len(channel.clients)
            return count

    def stop(self):
        self.stopped.set()
        try:
            self.listener.close()
        except OSError:
            pass
        with self.lock:
            channels, self.channels = self.channels, {}
        for channel in channels.values():
            for c in channel.clients:
                c.close()
