#!/usr/bin/env python3
"""Run Questlog Desktop for AION 2 under Proton, fed with live game traffic.

Questlog captures game traffic by calling libpcap functions in
C:\\Windows\\System32\\Npcap\\wpcap.dll. Npcap is a Windows driver that cannot
work under Wine, so this launcher puts our own wpcap.dll there (built from
bridge/wpcap_bridge.c) and feeds it from dumpcap on the Linux side:

    dumpcap per interface (TCP 13328) -> BridgeServer on 127.0.0.1 -> wpcap.dll -> Questlog

Questlog then runs its normal live capture loop, as on Windows, and picks
the interface whose address its game connection uses (Captures).

Run it as your normal user (dumpcap through the `wireshark` group). Questlog
opens at once, game or not.

While Questlog runs, its tray icon is ours (a2qlinux/tray.py, drawn by KDE):
Questlog's own icon is hidden because under Wine its menu opens only once.
"Quit Questlog" there ends Questlog once it has saved: at once if no game
data reached it in the last SAVE_WAIT seconds, else hidden at once and ended
SAVE_WAIT seconds after the last data; asking for it again before then keeps it running.
The desktop entry asks this launcher through signals (the PID is in the lock
file): SIGUSR1 = open Questlog's window, SIGUSR2 = keep Questlog running.
"""

import argparse
import collections
import os
from pathlib import Path
import re
import shutil
import shlex
import signal
import socket
import stat
import struct
import subprocess
import sys
import threading
import time

from . import config
from . import update as questlog_update
from .pcap_bridge import BridgeServer, read_records

APPID = 3393110
GAME_PORT = 13328
# The Windows parts, built by bridge/build.sh and shipped in the package.
BIN = Path(__file__).resolve().parent / "bin"
BRIDGE_DLL = BIN / "wpcap.dll"
# Marks our DLL in the prefix (kept from the project's first name: changing it
# would make install_bridge_dll take an installed build for a foreign file).
BRIDGE_SIGNATURE = b"questlog-proton bridge"


def log(message):
    print(f"[a2qlinux] {message}", flush=True)


# ---------------------------------------------------------------- processes

def _read(path, limit=262144):
    try:
        with open(path, "rb") as stream:
            return stream.read(limit).decode("utf-8", errors="replace")
    except OSError:
        return ""


def program_name(pid):
    """Lower-case file name of the program a process runs, from its command line.

    Wine puts the Windows path of the .exe in argv[0]. The kernel's `comm`
    is no use here: Chromium renames its processes (CrBrowserMain,
    CrGpuMain, ...), so Questlog never shows up under its own name there.
    """
    return exe_name(_read(f"/proc/{pid}/cmdline", 4096).split("\0", 1)[0])


def exe_name(argv0):
    """Lower-case file name in a Windows or Linux path."""
    return argv0.replace("\\", "/").rsplit("/", 1)[-1].lower()


def game_processes(appid, names):
    """PIDs of this user's processes in the game's Proton prefix, by program name.

    The prefix is recognised from the process environment (SteamAppId or the
    compatdata path), so a program of the same name elsewhere is not counted.
    """
    found = {name: set() for name in names}
    uid = str(os.getuid())
    for entry in os.scandir("/proc"):
        if not entry.name.isdigit():
            continue
        name = program_name(entry.name)
        if name not in found:
            continue
        status = dict(line.split(":", 1) for line in _read(f"/proc/{entry.name}/status").splitlines() if ":" in line)
        if status.get("Uid", "").split()[:1] != [uid] or status.get("State", "").strip()[:1] in {"Z", "X"}:
            continue
        env = dict(item.split("=", 1) for item in _read(f"/proc/{entry.name}/environ").split("\0") if "=" in item)
        in_game = any(env.get(key) == str(appid) for key in ("SteamAppId", "STEAM_APPID", "SteamGameId"))
        compat = env.get("STEAM_COMPAT_DATA_PATH", "")
        in_game |= bool(compat) and Path(compat).name == str(appid)
        if in_game:
            found[name].add(int(entry.name))
    return found


FLATPAK_STEAM = Path.home() / ".var" / "app" / "com.valvesoftware.Steam" / ".local" / "share" / "Steam"


def steam_roots(home=None):
    """Native Steam installations, each once.

    Valve's launcher keeps ~/.steam/steam (and ~/.steam/root) pointing at the
    installation, wherever the user or the distribution put it; the usual
    folders are listed after them for an installation without those links.
    """
    home = Path(home) if home else Path.home()
    data = Path(os.environ.get("XDG_DATA_HOME") or home / ".local" / "share")
    roots = []
    for candidate in (home / ".steam" / "steam", home / ".steam" / "root", data / "Steam", home / "Steam"):
        root = candidate.resolve()
        if root.is_dir() and root not in roots:
            roots.append(root)
    return roots


def game_prefix(appid, roots=None):
    """The game's Wine prefix.

    Read from a running AION2.exe's environment when there is one; otherwise
    looked up in Steam's library folders, the way Steam itself lays it out.
    """
    for pid in game_processes(appid, ["aion2.exe"])["aion2.exe"]:
        env = dict(item.split("=", 1) for item in _read(f"/proc/{pid}/environ").split("\0") if "=" in item)
        if env.get("WINEPREFIX"):
            return Path(env["WINEPREFIX"])
        if env.get("STEAM_COMPAT_DATA_PATH"):
            return Path(env["STEAM_COMPAT_DATA_PATH"]) / "pfx"
    roots = steam_roots() if roots is None else roots
    lists = [root / "steamapps" / "libraryfolders.vdf" for root in roots]
    for libraries in lists:
        for library in [Path(m) for m in re.findall(r'"path"\s+"([^"]+)"', _read(libraries))]:
            prefix = library / "steamapps" / "compatdata" / str(appid) / "pfx"
            if (prefix / "drive_c").is_dir():
                return prefix
    if not roots and FLATPAK_STEAM.is_dir():
        raise RuntimeError(f"Only a Flatpak Steam was found ({FLATPAK_STEAM}). A2Qlinux needs Steam from "
                           "the distribution's packages or from Valve; see docs/INSTALL.md.")
    looked = ", ".join(map(str, lists)) or "no Steam installation found"
    raise RuntimeError(f"AION 2's Wine prefix was not found in Steam's libraries ({looked}). "
                       "Start the game once from Steam so the prefix exists.")


def install_bridge_dll(prefix):
    """Put our wpcap.dll at C:\\Windows\\System32\\Npcap\\wpcap.dll in the game prefix.

    Replaces only what this project put there: the empty marker earlier
    versions created, or an older build of our DLL (recognised by its
    signature string). Any other file - a real Npcap, say - is left alone and
    reported, since overwriting it is not ours to decide.
    """
    if not BRIDGE_DLL.is_file():
        raise RuntimeError(f"{BRIDGE_DLL} is missing; in a source checkout build it with: bash bridge/build.sh")
    ours = BRIDGE_DLL.read_bytes()
    target = prefix / "drive_c" / "windows" / "system32" / "Npcap" / "wpcap.dll"
    if target.exists():
        current = target.read_bytes()
        if current == ours:
            return
        if current and BRIDGE_SIGNATURE not in current:
            raise RuntimeError(f"{target} is not ours (a real Npcap?); not replacing it. "
                               "Move it away if Questlog should use the Linux capture bridge.")
    target.parent.mkdir(exist_ok=True)
    temporary = target.with_suffix(".tmp")
    temporary.write_bytes(ours)
    temporary.replace(target)
    log(f"Installed the capture bridge DLL at {target}.")


def steam_launch_pending(appid):
    """True while Steam is starting the game and Proton waits for a free prefix.

    Steam starts the game with Proton's `waitforexitandrun` verb, which first
    waits (`wineserver -w`) until nothing runs in the game's Wine prefix any
    more. A Questlog started before the game keeps that prefix busy, so the
    game would wait for as long as Questlog runs. That Proton process stays
    on as the game's parent once the game runs, so a running AION2.exe means
    the launch is no longer pending.
    """
    if game_processes(appid, ["aion2.exe"])["aion2.exe"]:
        return False
    uid = str(os.getuid())
    for entry in os.scandir("/proc"):
        if not entry.name.isdigit():
            continue
        args = _read(f"/proc/{entry.name}/cmdline", 8192).split("\0")
        # Only Proton's own process counts: python3 <...>/proton waitforexitandrun <...>AION2.exe.
        # Steam's reaper and the runtime container carry the original command
        # line too, even after the a2qlinux-steam wrapper has switched Proton to "run".
        if len(args) < 4 or not Path(args[0]).name.startswith("python") or not args[1].endswith("/proton") \
                or args[2] != "waitforexitandrun" or not args[3].lower().endswith("aion2.exe"):
            continue
        status = dict(line.split(":", 1) for line in _read(f"/proc/{entry.name}/status").splitlines() if ":" in line)
        if status.get("Uid", "").split()[:1] != [uid]:
            continue
        env = dict(item.split("=", 1) for item in _read(f"/proc/{entry.name}/environ").split("\0") if "=" in item)
        if any(env.get(key) == str(appid) for key in ("SteamAppId", "STEAM_APPID", "SteamGameId")) \
                or Path(env.get("STEAM_COMPAT_DATA_PATH", "/")).name == str(appid):
            return True
    return False


def wait_for_game_or_cancel(appid):
    """After yielding to Steam: wait for the game, or for Steam to give up."""
    quiet_since = None
    while not game_processes(appid, ["aion2.exe"])["aion2.exe"]:
        if steam_launch_pending(appid):
            quiet_since = None
        elif quiet_since is None:
            quiet_since = time.monotonic()
        elif time.monotonic() - quiet_since >= 10:
            log("Steam is no longer starting AION 2; reopening Questlog without the game.")
            return
        time.sleep(0.5)
    time.sleep(2)
    log("AION 2 is running; reopening Questlog.")


# ------------------------------------------------------------------ capture

def system_dumpcap():
    found = shutil.which("dumpcap")
    if not found:
        raise RuntimeError("dumpcap is missing. Run a2qlinux-setup, which names the package to install.")
    path = Path(found).resolve(strict=True)
    info = path.stat()
    if info.st_uid != 0 or info.st_mode & (stat.S_IWGRP | stat.S_IWOTH):
        raise RuntimeError(f"{path} is not the root-owned dumpcap from the distribution.")
    return path


def interface_address(name):
    import fcntl
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        result = fcntl.ioctl(sock.fileno(), 0x8915, name.encode()[:15].ljust(256, b"\0"))
    return socket.inet_ntoa(result[20:24])


def usable_interfaces():
    """{name: IPv4 address} of every interface besides lo that has one."""
    usable = {}
    for _, name in socket.if_nameindex():
        if name == "lo":
            continue
        try:
            usable[name] = interface_address(name)
        except OSError:
            continue
    return usable


def start_dumpcap(dumpcap, interface, address):
    command = [str(dumpcap), "-i", interface, "-p", "-F", "pcap", "-q", "-s", "262144", "-B", "8",
               "--update-interval", "20", "-f", f"tcp and host {address} and port {GAME_PORT}", "-w", "-"]
    return subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, start_new_session=True)


def stop_process(process):
    if process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=3)


# Link types Questlog's frame decoder reads (Ethernet; BSD loopback; raw IP, as
# on WireGuard and OpenVPN tun); frames of any other type it skips without a word.
QUESTLOG_LINKTYPES = {1: "Ethernet", 0: "loopback", 108: "loopback", 12: "raw IP", 101: "raw IP"}


def pump_records(name, stream, server, status, capture, log=log):
    """Thread body: hand one interface's packets to the bridge; record how it ended."""
    try:
        for header, record in read_records(stream):
            if header is not None:
                linktype = struct.unpack("<I", header[20:24])[0]
                if linktype not in QUESTLOG_LINKTYPES:
                    log(f"Interface {name} delivers link type {linktype}, which Questlog cannot read "
                        f"(it reads {', '.join(sorted(set(QUESTLOG_LINKTYPES.values())))}); "
                        "game traffic on it will not be counted.")
            server.publish(name, header, record)
            if record is not None:
                status["packets"] += 1
                status["last_packet"] = time.monotonic()
        capture["error"] = "dumpcap stopped"
    except (ValueError, OSError) as error:
        capture["error"] = f"capture stream unreadable: {error}"


CAPTURE_SCAN_EVERY = 3   # s between looks at which interfaces are up (a VPN coming up or going down)
CAPTURE_RETRY_EVERY = 30  # s before a dumpcap that failed on an interface still up is tried again


def interface_index(name):
    """The kernel's index of an interface, or None when it is gone. An interface
    deleted and created again under the same name (a VPN switching servers)
    gets a new index, while a link going down and up keeps it."""
    try:
        return socket.if_nametoindex(name)
    except OSError:
        return None


def game_connection_addresses(path="/proc/net/tcp"):
    """Local IPv4 addresses of established connections to the game's port, from the kernel's table."""
    addresses = set()
    for line in _read(path, limit=4 << 20).splitlines()[1:]:
        fields = line.split()
        if len(fields) < 4 or fields[3] != "01":                # 01 = ESTABLISHED
            continue
        local, remote = fields[1], fields[2]
        if int(remote.split(":")[1], 16) != GAME_PORT:
            continue
        addresses.add(socket.inet_ntoa(struct.pack("<I", int(local.split(":")[0], 16))))
    return addresses


class Captures:
    """One dumpcap per usable interface, kept in step with the interfaces that are up.

    Each interface is a channel of the bridge; Questlog chooses among them by
    the address of its game connection (pcap_findalldevs), so whichever one
    the game uses - the network card, a VPN - is the one it reads. `wanted`
    (settings `interface`, --interface) limits capture to those names; empty
    means every interface with an IPv4 address besides lo.
    """

    def __init__(self, dumpcap, server, wanted, status, log=log, notify=None, interfaces=usable_interfaces,
                 start=None, game_addresses=game_connection_addresses, index_of=interface_index):
        self.dumpcap = dumpcap
        self.server = server
        self.wanted = tuple(wanted)
        self.status = status
        self.log = log
        self.notify = notify or (lambda text: None)
        self.interfaces = interfaces
        self.start = start or start_dumpcap
        self.game_addresses = game_addresses
        self.index_of = index_of
        self.reported = set()   # (name, address) whose failure was reported: once per launcher run
        self.told_uncaptured = set()
        self.running = {}       # name -> {"address", "index", "process", "error"}
        self.failed = {}        # name -> (address, retry at): dumpcap failed there; retried at that time,
                                # or at once when the address changes
        self.told_missing = set()
        self.told_none = False
        self.next_scan = 0.0

    def scan(self, now=None):
        now = time.monotonic() if now is None else now
        if now < self.next_scan:
            return
        self.next_scan = now + CAPTURE_SCAN_EVERY
        up = self.interfaces()
        every_address = set(up.values())     # before the settings' filter: which addresses exist at all
        if self.wanted:
            for name in self.wanted:
                if name not in up and name not in self.told_missing:
                    self.log(f"Interface {name} (from the settings) is not up or has no IPv4 address; "
                             f"capture starts on it when it comes up. Up now: {', '.join(up) or 'none'}.")
                    self.told_missing.add(name)
                elif name in up:
                    self.told_missing.discard(name)
            up = {name: address for name, address in up.items() if name in self.wanted}
        for name, capture in list(self.running.items()):
            if name not in up:
                self._stop(name)
                self.log(f"Interface {name} is gone (a VPN switched off?); capture there stopped.")
            elif up[name] != capture["address"]:
                self._stop(name)
                self.log(f"Interface {name} changed its address from {capture['address']} to {up[name]}; "
                         "capturing there again.")
            elif self.index_of(name) != capture["index"]:
                # Deleted and created again between two scans (a VPN switching servers takes
                # under a second): dumpcap ended with the old interface; not a failure.
                self._stop(name)
                self.log(f"Interface {name} was created anew (a VPN reconnecting?); capturing there again.")
            elif capture["process"].poll() is not None:
                self._stop(name)
                self.failed[name] = (capture["address"], now + CAPTURE_RETRY_EVERY)
                if (name, capture["address"]) in self.reported:
                    continue
                self.reported.add((name, capture["address"]))
                reason = capture["error"] or "dumpcap stopped"
                self.log(f"Capture on {name} ({capture['address']}) ended: {reason} "
                         f"(dumpcap exit code {capture['process'].returncode}; its own message is above). "
                         "Run a2qlinux-setup, which tests capture permission and says what to do. "
                         f"{name} is tried again every {CAPTURE_RETRY_EVERY} s, and at once when its "
                         "address changes; this is not reported again.")
                self.notify(f"Capture on {name} stopped, so Questlog gets no game data from it. "
                            "Details in the A2Qlinux window.")
        for name in [n for n, (address, retry_at) in self.failed.items()
                     if address != up.get(n) or now >= retry_at]:
            del self.failed[name]
        for name, address in up.items():
            if name in self.running or name in self.failed:
                continue
            self.server.add_interface(name, address)
            capture = {"address": address, "index": self.index_of(name),
                       "process": self.start(self.dumpcap, name, address), "error": None}
            self.running[name] = capture
            threading.Thread(target=pump_records, args=(name, capture["process"].stdout, self.server,
                                                         self.status, capture, self.log), daemon=True).start()
            self.log(f"Capturing on {name} ({address}), TCP port {GAME_PORT}.")
        if not up and not self.told_none:
            self.log("No network interface with an IPv4 address is up" + (" among those in the settings"
                     if self.wanted else "") + "; capture starts as soon as one is.")
            self.told_none = True
        elif up:
            self.told_none = False
        self._check_game_connection(every_address)

    def _check_game_connection(self, every_address):
        """Say so when the game's connection uses an address no capture covers: Questlog would get nothing."""
        captured = {capture["address"]: name for name, capture in self.running.items()}
        uncaptured = self.game_addresses() - set(captured)
        for address in uncaptured - self.told_uncaptured:
            if address not in every_address:
                # The kernel keeps a connection "established" after its address has gone (a VPN
                # switched off) until the game gives up on it; nothing passes there meanwhile.
                self.log(f"AION 2's connection to its server still uses {address}, which no network interface "
                         "has any more (a VPN switched off?). Nothing can pass on that connection: the game "
                         "has to reconnect, and Questlog follows it once it has.")
                self.notify(f"AION 2's connection lost its network ({address} is gone, a VPN switched off?); "
                            "the game has to reconnect.")
                continue
            why = (f"the setting 'interface' limits capture to {', '.join(self.wanted)}" if self.wanted
                   else "no capture runs on its interface")
            self.log(f"AION 2's connection to its server uses {address}, which A2Qlinux does not capture on "
                     f"({why}), so Questlog gets no game data. Capturing on: "
                     f"{', '.join(f'{n} ({a})' for a, n in captured.items()) or 'nothing'}.")
            self.notify(f"AION 2 uses {address}, which A2Qlinux does not capture on. Details in the A2Qlinux window.")
        self.told_uncaptured = uncaptured

    def _stop(self, name):
        capture = self.running.pop(name)
        self.server.remove_interface(name)
        stop_process(capture["process"])

    def stop(self):
        for name in list(self.running):
            self._stop(name)


# ------------------------------------------------------------------- session

def session_lock(directory):
    """Hold a lock for as long as this launcher runs; refuse a second launcher.

    A second launcher would start a second bridge and a second Questlog launch
    that hands over to the running one, which stays on the first bridge. The lock is released by
    the kernel when this process ends, however it ends.
    """
    import fcntl
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    fd = os.open(directory / ".lock", os.O_RDWR | os.O_CREAT | os.O_CLOEXEC, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        os.close(fd)
        raise RuntimeError("A2Qlinux is already running in another window; use that one.") from None
    # The desktop entry signals this PID (SIGUSR1/SIGUSR2) instead of starting a second launcher.
    os.ftruncate(fd, 0)
    os.pwrite(fd, f"{os.getpid()}\n".encode(), 0)
    return fd


# ----------------------------------------------------------- tray and quit

CTL = BIN / "questlog_ctl.exe"
SAVE_WAIT = 10.5   # s after the last game data before Questlog may be ended: it saves pending data within 10 s


class Requests:
    """What the user asked for: from our tray icon (a reader thread) and the desktop entry (signals).

    A deque, because its append and popleft are atomic and take no lock that
    a signal handler could interrupt.
    """

    def __init__(self):
        self._items = collections.deque()

    def put(self, item):
        self._items.append(item)

    def take(self):
        items = []
        while self._items:
            items.append(self._items.popleft())
        return items


class QuitControl:
    """Quitting from our tray icon, and the requests that call it off.

    Electron's session end - the only way to end Questlog from outside - skips
    Questlog's own saving, and Questlog writes pending data within 10 s of
    receiving it. So Questlog is ended SAVE_WAIT seconds after the last game
    data reached it: at once if that was long enough ago (no game, or the game
    closed), otherwise hidden at once - our icon goes, its window closes to the
    background - and ended when the time is up. Opening it again before then
    (SIGUSR1, our icon) or the game being started from Steam (SIGUSR2) calls
    the quit off.

    handle() returns the actions to carry out, in order:
      tray-off / tray-on   stop / start our tray icon
      close-window         hide Questlog's main window (only when ending is not immediate)
      show-window          show Questlog's main window
    """

    def __init__(self, save_wait=SAVE_WAIT):
        self.save_wait = save_wait
        self.due_at = None

    @property
    def quitting(self):
        return self.due_at is not None

    def handle(self, request, now, last_data=None):
        """last_data: monotonic time of the last game data Questlog received, or None."""
        if request == "quit":
            if self.quitting:
                return []
            self.due_at = max(now, last_data + self.save_wait) if last_data is not None else now
            return ["tray-off"] if self.due_at <= now else ["tray-off", "close-window"]
        if request == "open":
            if self.quitting:
                self.due_at = None
                return ["tray-on", "show-window"]
            return ["show-window"]
        if request == "keep":
            if self.quitting:
                self.due_at = None
                return ["tray-on"]
            return []
        raise ValueError(f"unknown request {request!r}")

    def due(self, now):
        return self.quitting and now >= self.due_at

    def reset(self):
        self.due_at = None


def run_ctl(protontricks, command, log_path):
    """Run questlog_ctl.exe <command> in the game prefix; log what it reports. Returns its exit code."""
    with log_path.open("ab") as wine_log:
        try:
            done = subprocess.run([protontricks, "--appid", str(APPID), str(CTL), command],
                                  stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=wine_log,
                                  timeout=120, start_new_session=True)
        except subprocess.TimeoutExpired:
            log(f"questlog_ctl.exe {command} did not finish within 120 s.")
            return -1
    lines = [line for line in done.stdout.decode("utf-8", "replace").splitlines() if line.strip()]
    for line in lines:
        log(f"Questlog control: {line}")
    if not lines:
        log(f"questlog_ctl.exe {command} printed nothing (exit code {done.returncode}); "
            f"Wine's output is in {log_path}.")
    return done.returncode


def run_ctl_async(protontricks, command, log_path):
    threading.Thread(target=run_ctl, args=(protontricks, command, log_path), daemon=True).start()


def hide_questlog_tray_icon(protontricks, log_path, timeout=60):
    """Hide Questlog's own tray icon once Questlog runs (in a thread).

    Not at the same moment as Questlog's launch: with no Wine session running
    yet, two protontricks-launch calls starting together can bring up two
    separate sessions in the prefix, and questlog_ctl.exe would then look for
    the icon in one where Questlog does not run.
    """
    def hide():
        deadline = time.monotonic() + timeout
        while not game_processes(APPID, ["questlog.exe"])["questlog.exe"]:
            if time.monotonic() > deadline:
                log(f"Questlog did not start within {timeout} s; its own tray icon was not hidden.")
                return
            time.sleep(0.5)
        time.sleep(2)
        run_ctl(protontricks, "hide-tray", log_path)
    threading.Thread(target=hide, daemon=True).start()


class Tray:
    """Our tray icon (a2qlinux/tray.py); what is chosen there goes into requests.

    It runs in its own session, so a Ctrl+C meant for this launcher does not
    reach it; it ends when its stdin closes. If it ends by itself, "tray-died"
    is put into requests so that Questlog's own icon can be shown again.
    """

    def __init__(self, requests):
        self.requests = requests
        self.process = None
        self.stopping = False

    def start(self):
        if self.process and self.process.poll() is None:
            return
        self.stopping = False
        self.process = subprocess.Popen([sys.executable, "-m", "a2qlinux.tray"], stdin=subprocess.PIPE,
                                        stdout=subprocess.PIPE, start_new_session=True)
        threading.Thread(target=self._read, args=(self.process,), daemon=True).start()

    def _read(self, process):
        for line in process.stdout:
            word = line.decode("utf-8", "replace").strip()
            if word in ("open", "quit"):
                self.requests.put(word)
        code = process.wait()
        if not self.stopping:
            log(f"Our tray icon stopped by itself (exit code {code}).")
            self.requests.put("tray-died")

    def stop(self):
        process, self.process = self.process, None
        if not process:
            return
        self.stopping = True
        try:
            process.stdin.close()
            process.wait(timeout=3)
        except (OSError, subprocess.TimeoutExpired):
            process.kill()
            process.wait(timeout=3)


def find_questlog_window():
    """X window id of Questlog's main window while it is shown, else None.

    Shown windows are in the window manager's _NET_CLIENT_LIST; a hidden one
    is not. Recognised by title "Questlog" and a _NET_WM_PID that is one of
    Questlog's processes (overlay windows are not managed, so not listed).
    """
    from Xlib import X, display
    screen = display.Display()
    try:
        pids = game_processes(APPID, ["questlog.exe"])["questlog.exe"]
        listed = screen.screen().root.get_full_property(screen.intern_atom("_NET_CLIENT_LIST"), X.AnyPropertyType)
        pid_atom = screen.intern_atom("_NET_WM_PID")
        for wid in (listed.value if listed else []):
            window = screen.create_resource_object("window", wid)
            try:
                name = window.get_wm_name()
                pid = window.get_full_property(pid_atom, X.AnyPropertyType)
            except Exception:      # the window went away meanwhile
                continue
            if isinstance(name, bytes):
                name = name.decode("utf-8", "replace")
            if name == "Questlog" and pid and pid.value[0] in pids:
                return wid
        return None
    finally:
        screen.close()


def activate_questlog_window(timeout=15):
    """Bring Questlog's main window to the front once it is shown.

    Questlog shows it itself when it is started a second time, but Wine does
    not let it take the focus (no recent user input in its process;
    docs/ARCHITECTURE.md §6.3), so KWin is asked instead, through
    _NET_ACTIVE_WINDOW (xdotool).
    """
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        wid = find_questlog_window()
        if wid:
            subprocess.run(["xdotool", "windowactivate", str(wid)], check=False)
            return True
        time.sleep(0.3)
    log(f"Questlog's window did not appear within {timeout} s of asking for it.")
    return False


def show_questlog_window(start_again):
    """Show Questlog's main window: start Questlog again - it hands over to the
    running copy, which shows its window - then bring that window to the front."""
    def show():
        start_again().wait()
        activate_questlog_window()
    threading.Thread(target=show, daemon=True).start()


# ------------------------------------------------------------------- launch

UPDATE_CHECK_EVERY = 6 * 3600   # s between checks for a new Questlog; set from config (update_check_hours)
UPDATE_CHECK_DEFER = 600        # s to wait while the game runs: no 115 MB download during play
UPDATE_TRIAL = 60               # s: a just-updated Questlog that exits sooner is rolled back


def notify(text):
    """Desktop notification, for what the user should know even with the terminal hidden."""
    subprocess.run(["notify-send", "--app-name=Questlog (AION 2)",
                    "--icon=" + str(Path.home() / ".local/share/icons/questlog-aion2.png"),
                    "Questlog (AION 2)", text], check=False)


def check_for_updates(questlog_dir, state_dir):
    """Thread body: stage new Questlog versions, never while the game runs."""
    time.sleep(60)
    while True:
        if game_processes(APPID, ["aion2.exe"])["aion2.exe"]:
            time.sleep(UPDATE_CHECK_DEFER)
            continue
        questlog_update.stage(questlog_dir, state_dir, log, notify)
        time.sleep(UPDATE_CHECK_EVERY)


GAME_EXIT_GRACE = 15      # s without AION2.exe before Questlog closes with the game; set from config (after_game_delay)
QUESTLOG_QUIT_WAIT = 20   # s for Questlog to quit after the session end


def wait_for_questlog_exit(saved_note):
    """After a session end: wait for all of Questlog's processes to go; stop any left over."""
    deadline = time.monotonic() + QUESTLOG_QUIT_WAIT
    while time.monotonic() < deadline:
        if not game_processes(APPID, ["questlog.exe"])["questlog.exe"]:
            log("Questlog closed.")
            return
        time.sleep(0.5)
    left = game_processes(APPID, ["questlog.exe"])["questlog.exe"]
    for pid in left:
        try:
            os.kill(pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
    log(f"Questlog did not quit within {QUESTLOG_QUIT_WAIT} s of the session end; "
        f"stopped its {len(left)} processes ({saved_note}).")


def wine_session_running(prefix):
    """True while a wineserver serves the game's prefix (WINEPREFIX, else STEAM_COMPAT_DATA_PATH/pfx)."""
    prefix = Path(prefix).resolve()
    uid = str(os.getuid())
    with os.scandir("/proc") as entries:
        for entry in entries:
            if not entry.name.isdigit() or _read(f"/proc/{entry.name}/comm").strip() != "wineserver":
                continue
            status = dict(line.split(":", 1) for line in _read(f"/proc/{entry.name}/status").splitlines() if ":" in line)
            if status.get("Uid", "").split()[:1] != [uid]:
                continue
            env = dict(item.split("=", 1) for item in _read(f"/proc/{entry.name}/environ").split("\0") if "=" in item)
            served = env.get("WINEPREFIX") or (env.get("STEAM_COMPAT_DATA_PATH", "") + "/pfx")
            if served and Path(served).resolve() == prefix:
                return True
    return False


SESSION_END_WAIT = 30   # s for the game's Wine session to close once Questlog has gone
STEAM_HELPER_WAIT = 5   # s for the game's steam.exe to end after SIGTERM
RELEASE_SETTLE = 2      # s the game's steam.exe must be alone in its launch before it is ended


def process_table():
    """{pid: (parent pid, kernel name, argv[0])} of this user's processes."""
    table = {}
    uid = str(os.getuid())
    with os.scandir("/proc") as entries:
        for entry in entries:
            if not entry.name.isdigit():
                continue
            status = dict(line.split(":", 1) for line in _read(f"/proc/{entry.name}/status").splitlines() if ":" in line)
            if status.get("Uid", "").split()[:1] != [uid] or status.get("State", "").strip()[:1] in {"Z", "X"}:
                continue
            table[int(entry.name)] = (int(status.get("PPid", "0").strip() or 0), status.get("Name", "").strip(),
                                      _read(f"/proc/{entry.name}/cmdline", 4096).split("\0", 1)[0])
    return table


def is_windows_program(argv0):
    """Wine puts the program's Windows path (C:\\…, Z:/…) in argv[0]."""
    return bool(re.match(r"[A-Za-z]:[\\/]", argv0))


def game_launch_state(table, steam_pids):
    """What is left of Steam's launch of the game once AION2.exe has gone: (state, detail).

    Steam counts the game as running until its `reaper` for the game ends,
    and that waits for every process below it (the runtime container's
    pv-adverb is a subreaper and lets nothing go). Below it are Proton's
    script and steam.exe, which waits until no ordinary program is left in
    the Wine session (docs/ARCHITECTURE.md §6.7). Whose launch started the
    session's wineserver decides what can be done:

      "free"     no steam.exe of the game is left: Steam already sees the game as closed
      "release"  only steam.exe is left in the game's launch: ending it releases Steam;
                 Questlog's session is elsewhere and stays (detail: steam.exe PIDs)
      "wait"     other Windows programs of the game's launch still run (detail: their names)
      "restart"  the Wine session itself was started by the game's launch, so it lives in
                 the launch until Questlog leaves it; or the launch cannot be told
                 (detail: why)
    """
    if not steam_pids:
        return "free", None
    reapers = set()
    for pid in steam_pids:
        ancestor = table.get(pid, (0,))[0]
        while ancestor in table and table[ancestor][1] != "reaper":
            ancestor = table[ancestor][0]
        if ancestor not in table:
            return "restart", f"steam.exe {pid} has no Steam reaper above it"
        reapers.add(ancestor)
    children = collections.defaultdict(list)
    for pid, (parent, _, _) in table.items():
        children[parent].append(pid)
    below, todo = [], list(reapers)
    while todo:
        pid = todo.pop()
        for child in children[pid]:
            below.append(child)
            todo.append(child)
    if any(table[pid][1] == "wineserver" for pid in below):
        return "restart", "the game's launch started the Wine session Questlog runs in"
    others = sorted({exe_name(table[pid][2]) for pid in below
                     if is_windows_program(table[pid][2]) and pid not in steam_pids})
    if others:
        return "wait", others
    return "release", set(steam_pids)


class AfterGame:
    """What to do after the game has exited, from game_launch_state, polled.

    next() returns one action, or None while there is nothing to do yet:
      "free"     Steam sees the game as closed already; Questlog stays as it is
      "release"  end the game's steam.exe; Questlog stays as it is
      "restart"  move Questlog out of the game's session and start it again

    steam.exe must have been alone for `settle` seconds before it is ended:
    a game that restarts itself goes through it. A restart ends Questlog
    without letting it save, so it waits until `save_wait` after the last
    game data reached Questlog (with the game closed, that is about when it
    closed).
    """

    def __init__(self, exited_at, save_wait=SAVE_WAIT, settle=RELEASE_SETTLE):
        self.exited_at = exited_at
        self.save_wait = save_wait
        self.settle = settle
        self.alone_since = None

    def restart_at(self, last_data=None):
        return max(self.exited_at, last_data + self.save_wait) if last_data is not None else self.exited_at

    def next(self, state, now, last_data=None):
        if state == "free":
            return "free"
        if state != "release":
            self.alone_since = None
            return "restart" if state == "restart" and now >= self.restart_at(last_data) else None
        if self.alone_since is None:
            self.alone_since = now
        return "release" if now - self.alone_since >= self.settle else None


def end_game_steam_helper(why, pids=None):
    """End the game's steam.exe (those in `pids`, else every one of the game's). Returns how many were ended.

    SIGTERM ends it and, with it, Proton's script, the runtime container and
    Steam's reaper, exactly as Steam's own Stop does. Tested both after the
    game's Wine session had closed (where steam.exe was seen sleeping on in
    ntsync waits the server's exit does not wake) and with Questlog's session
    still running, which it leaves alone (§6.7).
    """
    orphans = set(pids) if pids is not None else game_processes(APPID, ["steam.exe"])["steam.exe"]
    for pid in orphans:
        try:
            os.kill(pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
    deadline = time.monotonic() + STEAM_HELPER_WAIT
    while orphans and time.monotonic() < deadline and game_processes(APPID, ["steam.exe"])["steam.exe"] & orphans:
        time.sleep(0.2)
    left = game_processes(APPID, ["steam.exe"])["steam.exe"] & orphans
    if orphans:
        log(f"Ended {len(orphans) - len(left)} of {len(orphans)} steam.exe left over from the game's launch "
            f"{why}; Steam sees AION 2 as closed now."
            + (f" Still running: {sorted(left)} - use Stop in Steam." if left else ""))
    return len(orphans) - len(left)


def move_to_fresh_session(prefix, protontricks, log_path):
    """End Questlog and wait until the game's Wine session is gone. Returns True if it went.

    Proton's steam.exe, which started the game, waits until no ordinary
    program is left in the Wine session - Questlog included - and Steam shows
    the game as running until then (docs/ARCHITECTURE.md §6.7). Ending
    Questlog lets the session close and Steam see the game end; the caller
    then starts Questlog again in a session of its own.
    """
    run_ctl(protontricks, "end-session", log_path)
    wait_for_questlog_exit(f"it had {SAVE_WAIT:.0f} s since the last game data to save")
    return release_steam_after_questlog(prefix, "Questlog starts again anyway.")


def release_steam_after_questlog(prefix, then=""):
    """Once Questlog has been ended with the game gone: let Steam see the game end. True if it does.

    Ending Questlog lets the game's Wine session close, but the game's
    steam.exe was seen sleeping on after that, never woken (§6.7, step 3b),
    and Steam then shows AION 2 as running for hours. So wait for the session
    to close and end any steam.exe of the game left over. Nothing to do, and
    no wait, while the game runs or when no steam.exe of it is left.
    """
    if game_processes(APPID, ["aion2.exe"])["aion2.exe"] or not game_processes(APPID, ["steam.exe"])["steam.exe"]:
        return True
    deadline = time.monotonic() + SESSION_END_WAIT
    while time.monotonic() < deadline:
        if not wine_session_running(prefix):
            end_game_steam_helper("after its Wine session had closed")
            return True
        time.sleep(0.5)
    log(f"The game's Wine session is still open {SESSION_END_WAIT} s after Questlog left it: another "
        "program in the prefix keeps it (e.g. a second meter), and Steam shows AION 2 as running "
        f"until that program ends. {then}".rstrip())
    return False


def close_questlog(prefix, protontricks, log_path):
    """Close Questlog after the game has gone, the way Windows does at log-off.

    Closing its window only hides Questlog to the tray. A session end
    (`wineboot -e`) makes it quit; it went in 2-3 s when measured. Questlog
    keeps unsaved changes for at most 10 s (combat data) and 0.5 s (settings),
    so after GAME_EXIT_GRACE nothing is lost even if it has to be stopped hard.
    The wineboot launcher itself does not return once the session has ended,
    so it is stopped here as soon as Questlog is gone.
    """
    wineboot = prefix / "drive_c" / "windows" / "system32" / "wineboot.exe"
    with log_path.open("ab") as out:
        ender = subprocess.Popen([protontricks, "--appid", str(APPID), str(wineboot), "-e"],
                                 stdin=subprocess.DEVNULL, stdout=out, stderr=subprocess.STDOUT,
                                 start_new_session=True)
    try:
        wait_for_questlog_exit(f"its data had been saved for {GAME_EXIT_GRACE} s")
    finally:
        try:
            os.killpg(ender.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        try:
            ender.wait(timeout=5)
        except subprocess.TimeoutExpired:
            os.killpg(ender.pid, signal.SIGKILL)
            ender.wait(timeout=5)


class QuestlogLaunch:
    """Questlog started so that its launch outlives it while the Wine session is in use (§5.1).

    protontricks ends the Steam Runtime container of a call once the call's
    command returns, and everything started in it with it. Questlog's launch
    usually brings up the prefix's Wine session - wineserver, services,
    explorer.exe - inside that container, and the game joins it; a call that
    ended with Questlog took the game's session along and froze the game. So
    the call runs `wine Questlog.exe …; echo $? > exit_file; wineserver -w`:
    the shell records Questlog's own exit code, then waits until the session
    has ended. poll(), wait() and returncode follow Questlog itself - the
    exit file - or the call, if that ends first (protontricks failed).
    """

    def __init__(self, process, exit_file):
        self.process = process
        self.exit_file = Path(exit_file)
        self.returncode = None

    def poll(self):
        if self.returncode is None:
            text = _read(self.exit_file).strip()
            if text:
                self.returncode = int(text) if text.lstrip("-").isdigit() else -1
            elif self.process.poll() is not None:
                self.returncode = self.process.returncode
        return self.returncode

    def wait(self, timeout=None):
        deadline = None if timeout is None else time.monotonic() + timeout
        while self.poll() is None:
            if deadline is not None and time.monotonic() >= deadline:
                raise subprocess.TimeoutExpired("Questlog", timeout)
            time.sleep(0.2)
        return self.returncode


def launch_questlog(executable, server, protontricks, log_path, hidden=False, hold_session=True):
    """Start Questlog in the game prefix; a QuestlogLaunch (hold_session) or the bare launch.

    hold_session=False is for a second start that only hands a request over
    to the running Questlog and ends at once (show_questlog_window): it must
    not wait for the session.
    """
    env = os.environ.copy()
    env["QUESTLOG_PROTON_BRIDGE"] = server.environment_value()
    # Wine ships a builtin wpcap.dll and loads it instead of ours even when
    # Questlog names our file by full path; "n" makes it take the native file.
    overrides = [o for o in env.get("WINEDLLOVERRIDES", "").split(";") if o and not o.startswith("wpcap=")]
    env["WINEDLLOVERRIDES"] = ";".join(overrides + ["wpcap=n"])
    env["PWD"] = str(executable.parent)
    # Inside Steam's container (pressure-vessel) Chromium cannot set up its
    # Windows sandbox: the GPU process fails with error 39 and the renderers
    # never start, so Questlog quits or shows no pages. Wine does not enforce
    # the Windows security boundaries that sandbox relies on in any case.
    # --hidden is Questlog's own switch: start with its window hidden, tray only.
    extra = ["--hidden"] if hidden else []
    output = dict(cwd=str(executable.parent), env=env, start_new_session=True,
                  stdin=subprocess.DEVNULL, stdout=log_path.open("ab"), stderr=subprocess.STDOUT)
    if not hold_session:
        return subprocess.Popen([protontricks, "--appid", str(APPID), str(executable), "--no-sandbox", *extra],
                                **output)
    exit_file = log_path.with_name("questlog.exit")
    exit_file.unlink(missing_ok=True)
    command = " ".join(["wine", shlex.quote(str(executable)), "--no-sandbox", *extra]) \
        + f"; echo $? > {shlex.quote(str(exit_file))}; wineserver -w"
    beside = Path(protontricks).with_name("protontricks")
    tool = str(beside) if beside.is_file() else (shutil.which("protontricks") or "protontricks")
    # No background wineserver: its keepalive program stays in the session until
    # the call ends, and `wineserver -w` would wait for it for ever.
    call = [tool, "--no-background-wineserver", "-c", command, str(APPID)]
    # A scope of its own: whatever ends the launcher - a quit, or the
    # systemd-run service the Steam launch option starts it in - must not take
    # the session along. The call stays this process's child either way.
    if shutil.which("systemd-run"):
        call = ["systemd-run", "--user", "--scope", "--quiet", "--collect",
                f"--unit=questlog-{os.getpid()}-{time.monotonic_ns()}", *call]
    return QuestlogLaunch(subprocess.Popen(call, **output), exit_file)


def main():
    global GAME_EXIT_GRACE, UPDATE_CHECK_EVERY
    settings, config_problems = config.load()
    GAME_EXIT_GRACE = settings.after_game_delay
    UPDATE_CHECK_EVERY = settings.update_check_hours * 3600
    default_exe = settings.questlog_dir / "Questlog.exe"
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter,
                                     epilog=f"Settings file: {config.CONFIG_PATH} (options here override it).")
    parser.add_argument("--exe", type=Path, default=default_exe, help=f"Questlog.exe (default {default_exe})")
    parser.add_argument("--interface", action="append", metavar="NAME",
                        help="capture only on this network interface (repeat for several; default: every "
                             "interface with an IPv4 address, and Questlog follows the game's connection)")
    parser.add_argument("--no-auto-update", action="store_true",
                        help="do not download or install new Questlog versions (default: download them "
                             "in the background and install them at the next start)")
    parser.add_argument("--close-with-game", action="store_true",
                        help=f"close Questlog {GAME_EXIT_GRACE} s after AION 2 exits "
                             "(default: Questlog stays open, e.g. to look through fights afterwards)")
    args = parser.parse_args()
    close_with_game = args.close_with_game or settings.after_game == "close"
    auto_update = settings.auto_update and not args.no_auto_update
    for problem in config_problems:
        log(f"Settings: {problem}")
    if config_problems:
        notify(f"{len(config_problems)} problem(s) in {config.CONFIG_PATH}; defaults used for those settings. "
               "Details in the A2Qlinux window.")
    if os.geteuid() == 0:
        parser.error("Run as your normal user, without sudo.")
    executable = args.exe.expanduser().resolve()
    if not executable.is_file():
        parser.error(f"{executable} not found; install Questlog there or pass --exe.")
    protontricks = shutil.which("protontricks-launch")
    if not protontricks:
        parser.error("protontricks-launch not found; install the native protontricks package.")
    requests = Requests()
    # Before the PID is published in the lock file: the default action of both would end this launcher.
    signal.signal(signal.SIGUSR1, lambda *_: requests.put("open"))
    signal.signal(signal.SIGUSR2, lambda *_: requests.put("keep"))
    try:
        state_dir = executable.parent / "proton-stream"
        session_lock(state_dir)
        dumpcap = system_dumpcap()
        running = game_processes(APPID, ["questlog.exe"])["questlog.exe"]
        if running:
            fed = any("QUESTLOG_PROTON_BRIDGE=" in _read(f"/proc/{pid}/environ") for pid in running)
            if fed:
                raise RuntimeError("Questlog is already running and fed by another A2Qlinux "
                                   "(another terminal window). Nothing to do here.")
            raise RuntimeError("Questlog is already running in the game prefix without the capture bridge. "
                               "Quit it (tray icon > Quit) and run this again.")
        server = BridgeServer(log)
        status = {"packets": 0}
        captures = Captures(dumpcap, server, args.interface or settings.interface, status, notify=notify)
        captures.scan()
        tray = None
        try:
            game_seen = bool(game_processes(APPID, ["aion2.exe"])["aion2.exe"])
            prefix = game_prefix(APPID)
            install_bridge_dll(prefix)
            if game_seen:
                log("AION 2 is running; starting Questlog.")
            else:
                log("AION 2 is not running; starting Questlog now (saved fights, database, map). "
                    "Start the game any time - its traffic then flows to Questlog.")
            log_path = state_dir / "questlog.log"
            log_path.write_bytes(b"")          # one log per launcher run; relaunches append
            tray = Tray(requests)
            quit_control = QuitControl()

            trial = {"until": 0.0}      # end of a just-installed update's trial run

            def start_questlog(hidden=False):
                # A fresh Questlog shows its window (unless hidden); earlier "open" requests are answered by that.
                requests.take()
                questlog_update.disable_builtin_updater(executable.parent, log)
                if auto_update and questlog_update.install_staged(executable.parent, state_dir, log):
                    trial["until"] = time.monotonic() + UPDATE_TRIAL
                log(f"Starting Questlog {questlog_update.installed_version(executable.parent) or '(version unknown)'}.")
                started = launch_questlog(executable, server, protontricks, log_path, hidden=hidden)
                tray.start()
                hide_questlog_tray_icon(protontricks, log_path)
                return started

            def start_again():
                return launch_questlog(executable, server, protontricks, log_path, hold_session=False)

            questlog = start_questlog()
            if auto_update:
                threading.Thread(target=check_for_updates, args=(executable.parent, state_dir), daemon=True).start()
            told = False
            game_gone_since = None
            after_exit = None
            told_waiting = False
            closing = False
            while True:
                if questlog.poll() is not None:
                    if time.monotonic() < trial["until"]:
                        trial["until"] = 0.0
                        version = questlog_update.installed_version(executable.parent)
                        log(f"Questlog {version} ended within {UPDATE_TRIAL} s of its first start after the update "
                            f"(code {questlog.returncode}); going back to the previous version.")
                        tray.stop()
                        if questlog_update.rollback(executable.parent, state_dir, log):
                            notify(f"Questlog {version} did not start under Proton; went back to the previous "
                                   "version. Details in the terminal window.")
                            questlog = start_questlog()
                            continue
                    break
                for request in requests.take():
                    if request == "tray-died":
                        log("Showing Questlog's own tray icon again, so it can still be quit.")
                        run_ctl_async(protontricks, "show-tray", log_path)
                        continue
                    was_quitting = quit_control.quitting
                    for action in quit_control.handle(request, time.monotonic(), status.get("last_packet")):
                        if action == "tray-off":
                            tray.stop()
                        elif action == "tray-on":
                            tray.start()
                        elif action == "close-window":
                            run_ctl_async(protontricks, "close-window", log_path)
                        elif action == "show-window":
                            show_questlog_window(start_again)
                    if request == "quit" and not was_quitting:
                        left = max(0.0, quit_control.due_at - time.monotonic())
                        if left > 0.5:
                            log(f"Quitting Questlog: hidden now, ended in {left:.0f} s, once it has saved the "
                                "last game data. Open it again before then and it keeps running.")
                        else:
                            log("Quitting Questlog now (no game data in the last "
                                f"{SAVE_WAIT:.0f} s, so nothing is waiting to be saved).")
                    elif request in ("open", "keep") and was_quitting:
                        log("Quit called off: Questlog was asked for again; it keeps running.")
                    elif request == "open":
                        log("Opening Questlog's window (asked from our tray icon or its menu entry).")
                    elif request == "keep":
                        log("The game is being started from Steam; Questlog keeps running.")
                if quit_control.due(time.monotonic()):
                    log("Ending Questlog's session now.")
                    run_ctl(protontricks, "end-session", log_path)
                    wait_for_questlog_exit(f"it had {SAVE_WAIT:.0f} s since the last game data to save")
                    release_steam_after_questlog(prefix)
                    try:
                        questlog.wait(timeout=30)
                    except subprocess.TimeoutExpired:
                        log("The Questlog launcher did not end after Questlog quit; continuing anyway.")
                    quit_control.reset()
                    if any(r in ("open", "keep") for r in requests.take()):
                        log("Questlog was asked for again while it was ending; starting it again.")
                        questlog = start_questlog()
                        told = False
                        continue
                    log("Questlog has quit.")
                    return 0
                if not game_seen and steam_launch_pending(APPID):
                    log("Steam is starting AION 2 and waits until nothing else runs in the game's "
                        "Wine prefix; closing Questlog now - it reopens once the game runs.")
                    tray.stop()
                    quit_control.reset()
                    close_questlog(prefix, protontricks, log_path)
                    try:
                        questlog.wait(timeout=30)
                    except subprocess.TimeoutExpired:
                        log("The previous Questlog launcher did not end; continuing anyway.")
                    wait_for_game_or_cancel(APPID)
                    game_seen = bool(game_processes(APPID, ["aion2.exe"])["aion2.exe"])
                    questlog = start_questlog()
                    told = False
                    continue
                captures.scan()
                if not told and status["packets"] and server.client_count():
                    log("Game traffic is flowing to Questlog.")
                    told = True
                if game_processes(APPID, ["aion2.exe"])["aion2.exe"]:
                    if not game_seen:
                        log("AION 2 has started.")
                    elif game_gone_since is not None:
                        log("AION 2 is running again.")
                    game_seen = True
                    game_gone_since = None
                    after_exit = None
                elif not game_seen:
                    pass
                elif game_gone_since is None:
                    game_gone_since = time.monotonic()
                    after_exit = AfterGame(game_gone_since)
                    told_waiting = False
                    if close_with_game:
                        log(f"AION 2 has exited; closing Questlog in {GAME_EXIT_GRACE} s unless the game comes back.")
                    else:
                        log("AION 2 has exited; Questlog stays open and waits for the next start of the game.")
                elif close_with_game:
                    if not closing and time.monotonic() - game_gone_since >= GAME_EXIT_GRACE:
                        closing = True
                        tray.stop()
                        close_questlog(prefix, protontricks, log_path)
                        release_steam_after_questlog(prefix)
                elif not quit_control.quitting:
                    steam_pids = game_processes(APPID, ["steam.exe"])["steam.exe"]
                    state, detail = game_launch_state(process_table(), steam_pids)
                    action = after_exit.next(state, time.monotonic(), status.get("last_packet"))
                    if state == "wait" and not told_waiting \
                            and time.monotonic() - game_gone_since >= RELEASE_SETTLE + 3:
                        log(f"Steam shows AION 2 as running while {', '.join(detail)} from the game's launch "
                            "still runs; it is ended as soon as that program ends.")
                        told_waiting = True
                    elif state == "restart" and not told_waiting:
                        left = max(0.0, after_exit.restart_at(status.get("last_packet")) - time.monotonic())
                        log(f"Questlog restarts in {left:.0f} s, once it has saved the last game data: {detail}, "
                            "so Steam shows AION 2 as running for as long as Questlog stays in that session.")
                        told_waiting = True
                    if action == "free":
                        log("Steam sees AION 2 as closed; Questlog keeps running.")
                    elif action == "release":
                        end_game_steam_helper("- the only thing left of it, as Questlog's Wine session is "
                                              "its own; Questlog keeps running", detail)
                    elif action == "restart":
                        shown = find_questlog_window() is not None
                        log("Moving Questlog out of the game's Wine session; back in a few seconds"
                            + (" with its window open." if shown else ", in the tray."))
                        move_to_fresh_session(prefix, protontricks, log_path)
                        try:
                            questlog.wait(timeout=30)
                        except subprocess.TimeoutExpired:
                            log("The previous Questlog launcher did not end; continuing anyway.")
                        questlog = start_questlog(hidden=not shown)
                        told = False
                    if action:
                        game_seen = False
                        game_gone_since = None
                        after_exit = None
                        if action == "restart":
                            continue
                time.sleep(0.5)
            log(f"Questlog has exited (code {questlog.returncode}); its output is in {log_path}.")
            return 0
        finally:
            if tray:
                tray.stop()
                # Ending while Questlog runs on (Ctrl+C, an error): give it its own tray icon back.
                if game_processes(APPID, ["questlog.exe"])["questlog.exe"]:
                    run_ctl(protontricks, "show-tray", log_path)
            captures.stop()
            server.stop()
    except (OSError, RuntimeError) as error:
        print(f"a2qlinux: {error}", file=sys.stderr)
        return 1


def run():
    """Entry point (python -m a2qlinux.launcher, a2qlinux-run)."""
    try:
        return main()
    except KeyboardInterrupt:
        print("\nStopped. Questlog keeps running without live traffic; quit it from its own tray icon, "
              "which is shown again.", file=sys.stderr)
        return 130


if __name__ == "__main__":
    sys.exit(run())
