"""Serve captured packets to the wpcap.dll stand-in inside Proton.

The DLL (bridge/wpcap_bridge.c) connects to this server on 127.0.0.1, sends
"QLPB1 <token>\\n" and then receives a classic pcap stream: the 24-byte global
header, followed by packet records (16-byte record header + frame). Each
pcap_open_live in Questlog is one such connection; Questlog opens a new one
when the game's connections change and only then closes the old, so several
clients can be connected at once and each gets every packet.

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

HELLO_PREFIX = b"QLPB1 "
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


class BridgeServer:
    """Accept authenticated DLL connections and fan packet records out to them."""

    def __init__(self, log, host="127.0.0.1"):
        self.log = log
        self.token = secrets.token_hex(32)
        self.listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.listener.bind((host, 0))
        self.listener.listen(8)
        self.host, self.port = self.listener.getsockname()
        self.global_header = None
        self.header_ready = threading.Event()
        self.clients = []
        self.lock = threading.Lock()
        self.connections = 0
        self.stopped = threading.Event()
        threading.Thread(target=self._accept_loop, daemon=True).start()

    def environment_value(self, local_ip):
        """The QUESTLOG_PROTON_BRIDGE value the DLL reads."""
        return f"{self.host}:{self.port}:{self.token}:{local_ip}"

    def _accept_loop(self):
        while not self.stopped.is_set():
            try:
                sock, peer = self.listener.accept()
            except OSError:
                return
            threading.Thread(target=self._admit, args=(sock, peer), daemon=True).start()

    def _admit(self, sock, peer):
        try:
            sock.settimeout(5)
            line = b""
            while not line.endswith(b"\n") and len(line) < 200:
                chunk = sock.recv(200 - len(line))
                if not chunk:
                    break
                line += chunk
            expected = HELLO_PREFIX + self.token.encode() + b"\n"
            if not hmac.compare_digest(line, expected):
                self.log(f"Refused a connection from {peer[0]}:{peer[1]} without the right token.")
                sock.close()
                return
            if not self.header_ready.wait(timeout=5):
                self.log("Questlog connected before dumpcap started; it will retry.")
                sock.close()
                return
            sock.settimeout(None)
            sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            client = _Client(sock, peer, self.global_header, self.log)
        except OSError:
            sock.close()
            return
        with self.lock:
            self.clients.append(client)
            self.connections += 1
            count = self.connections
        # Questlog reconnects by design on every zone change (it opens the new
        # device before closing the old one), so only the first connection is
        # worth a line; what is abnormal (refused, dropped) is logged above.
        if count == 1:
            self.log("Questlog connected to the capture bridge.")

    def publish(self, global_header, record):
        """Feed one item from read_records()."""
        if global_header is not None:
            self.global_header = global_header
            self.header_ready.set()
            return
        with self.lock:
            self.clients = [c for c in self.clients if c.offer(record)]

    def client_count(self):
        with self.lock:
            self.clients = [c for c in self.clients if not c.closed.is_set()]
            return len(self.clients)

    def stop(self):
        self.stopped.set()
        try:
            self.listener.close()
        except OSError:
            pass
        with self.lock:
            for c in self.clients:
                c.close()
            self.clients = []
