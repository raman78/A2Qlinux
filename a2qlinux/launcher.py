#!/usr/bin/env python3
"""Run Questlog Desktop for AION 2 under Proton, fed with live game traffic.

Questlog captures game traffic by calling libpcap functions in
C:\\Windows\\System32\\Npcap\\wpcap.dll. Npcap is a Windows driver that cannot
work under Wine, so this launcher puts our own wpcap.dll there (built from
bridge/wpcap_bridge.c) and feeds it from dumpcap on the Linux side:

    dumpcap (TCP 13328) -> BridgeServer on 127.0.0.1 -> wpcap.dll -> Questlog

Questlog then runs its normal live capture loop, as on Windows.

Run it as your normal user (dumpcap through the `wireshark` group). Questlog
opens at once, game or not; with --wait-for-game only once the game runs.

While Questlog runs, its tray icon is ours (a2qlinux/tray.py, drawn by KDE):
Questlog's own icon is hidden because under Wine its menu opens only once.
"Quit Questlog" there hides Questlog at once and ends it SAVE_WAIT seconds
later, once it has saved; asking for it again before then keeps it running.
The desktop entry asks this launcher through signals (the PID is in the lock
file): SIGUSR1 = open Questlog's window, SIGUSR2 = keep Questlog running.
"""

import argparse
import collections
import os
from pathlib import Path
import re
import shutil
import signal
import socket
import stat
import subprocess
import sys
import threading
import time

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
# Where Questlog's files were unpacked; QUESTLOG_DIR overrides (see a2qlinux-setup).
QUESTLOG_DIR = Path(os.environ.get("QUESTLOG_DIR") or Path.home() / "Games" / "Questlog").expanduser()
DEFAULT_EXE = QUESTLOG_DIR / "Questlog.exe"


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
    argv0 = _read(f"/proc/{pid}/cmdline", 4096).split("\0", 1)[0]
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


def game_prefix(appid):
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
    libraries = Path.home() / ".local" / "share" / "Steam" / "steamapps" / "libraryfolders.vdf"
    candidates = [Path(m) for m in re.findall(r'"path"\s+"([^"]+)"', _read(libraries))]
    for library in candidates:
        prefix = library / "steamapps" / "compatdata" / str(appid) / "pfx"
        if (prefix / "drive_c").is_dir():
            return prefix
    raise RuntimeError(f"AION 2's Wine prefix was not found in Steam's libraries ({libraries}). "
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


def wait_for_game(appid):
    """Return once AION2.exe has been running for two seconds."""
    seen_since = None
    told = False
    while True:
        running = game_processes(appid, ["aion2.exe"])["aion2.exe"]
        now = time.monotonic()
        if running:
            seen_since = seen_since or now
            if now - seen_since >= 2:
                return
        else:
            seen_since = None
            if not told:
                log("Waiting for AION 2. Press Play in Steam; Questlog opens once the game runs.")
                told = True
        time.sleep(0.5)


# ------------------------------------------------------------------ capture

def system_dumpcap():
    found = shutil.which("dumpcap")
    if not found:
        raise RuntimeError("dumpcap is missing. Install wireshark-cli.")
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


def choose_interface(requested):
    usable = {}
    for _, name in socket.if_nameindex():
        if name == "lo":
            continue
        try:
            usable[name] = interface_address(name)
        except OSError:
            continue
    if requested:
        if requested not in usable:
            raise RuntimeError(f"Interface {requested} has no IPv4 address. Usable: {', '.join(usable) or 'none'}.")
        return requested, usable[requested]
    if len(usable) == 1:
        return next(iter(usable.items()))
    if not usable:
        raise RuntimeError("No network interface with an IPv4 address was found.")
    raise RuntimeError(f"Several interfaces are up ({', '.join(usable)}); choose one with --interface.")


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


def pump_records(stream, server, status):
    """Thread body: hand dumpcap's packets to the bridge; record how it ended."""
    try:
        for header, record in read_records(stream):
            server.publish(header, record)
            if record is not None:
                status["packets"] += 1
        status["error"] = "dumpcap stopped. Check capture permission: dumpcap -D"
    except (ValueError, OSError) as error:
        status["error"] = f"Capture stream unreadable: {error}"


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
SAVE_WAIT = 12   # s from "Quit Questlog" to its end: Questlog saves pending data within 10 s


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

    "Quit Questlog" does not end Questlog at once: Electron's session end
    (the only way to end it from outside) skips Questlog's own saving, and
    Questlog writes pending data only every 10 s. So it is hidden at once -
    our icon goes, its window closes to the background - and ended SAVE_WAIT
    seconds later. Opening it again before then (SIGUSR1, our icon) or the
    game being started from Steam (SIGUSR2) calls the quit off.

    handle() returns the actions to carry out, in order:
      tray-off / tray-on   stop / start our tray icon
      close-window         hide Questlog's main window
      show-window          show Questlog's main window
    """

    def __init__(self, save_wait=SAVE_WAIT):
        self.save_wait = save_wait
        self.quitting_since = None

    @property
    def quitting(self):
        return self.quitting_since is not None

    def handle(self, request, now):
        if request == "quit":
            if self.quitting:
                return []
            self.quitting_since = now
            return ["tray-off", "close-window"]
        if request == "open":
            if self.quitting:
                self.quitting_since = None
                return ["tray-on", "show-window"]
            return ["show-window"]
        if request == "keep":
            if self.quitting:
                self.quitting_since = None
                return ["tray-on"]
            return []
        raise ValueError(f"unknown request {request!r}")

    def due(self, now):
        return self.quitting and now - self.quitting_since >= self.save_wait

    def reset(self):
        self.quitting_since = None


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

UPDATE_CHECK_EVERY = 6 * 3600   # s between checks for a new Questlog
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


GAME_EXIT_GRACE = 15      # s without AION2.exe before Questlog is closed
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


def move_to_fresh_session(prefix, protontricks, log_path):
    """End Questlog and wait until the game's Wine session is gone. Returns True if it went.

    Proton's steam.exe, which started the game, waits until no ordinary
    program is left in the Wine session - Questlog included - and Steam shows
    the game as running until then (docs/ARCHITECTURE.md §6.7). Ending
    Questlog lets the session close and Steam see the game end; the caller
    then starts Questlog again in a session of its own.
    """
    run_ctl(protontricks, "end-session", log_path)
    wait_for_questlog_exit("the game had been closed for "
                           f"{GAME_EXIT_GRACE} s, so its data was saved")
    deadline = time.monotonic() + SESSION_END_WAIT
    while time.monotonic() < deadline:
        if not wine_session_running(prefix):
            return True
        time.sleep(0.5)
    log(f"The game's Wine session is still open {SESSION_END_WAIT} s after Questlog left it: another "
        "program in the prefix keeps it (e.g. a second meter), and Steam shows AION 2 as running "
        "until that program ends. Questlog starts again anyway.")
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


def launch_questlog(executable, server, address, protontricks, log_path, hidden=False):
    env = os.environ.copy()
    env["QUESTLOG_PROTON_BRIDGE"] = server.environment_value(address)
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
    return subprocess.Popen([protontricks, "--appid", str(APPID), str(executable), "--no-sandbox", *extra],
                            cwd=str(executable.parent), env=env, start_new_session=True,
                            stdin=subprocess.DEVNULL, stdout=log_path.open("ab"), stderr=subprocess.STDOUT)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--exe", type=Path, default=DEFAULT_EXE, help=f"Questlog.exe (default {DEFAULT_EXE})")
    parser.add_argument("--interface", help="network interface carrying the game connection")
    parser.add_argument("--wait-for-game", action="store_true",
                        help="start Questlog only once AION 2 runs (the Steam launch option uses this); "
                             "default: start it at once, e.g. to look through saved fights")
    parser.add_argument("--no-auto-update", action="store_true",
                        help="do not download or install new Questlog versions (default: download them "
                             "in the background and install them at the next start)")
    parser.add_argument("--close-with-game", action="store_true",
                        help=f"close Questlog {GAME_EXIT_GRACE} s after AION 2 exits "
                             "(default: Questlog stays open, e.g. to look through fights afterwards)")
    args = parser.parse_args()
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
        interface, address = choose_interface(args.interface)
        running = game_processes(APPID, ["questlog.exe"])["questlog.exe"]
        if running:
            fed = any("QUESTLOG_PROTON_BRIDGE=" in _read(f"/proc/{pid}/environ") for pid in running)
            if fed:
                raise RuntimeError("Questlog is already running and fed by another A2Qlinux "
                                   "(another terminal window). Nothing to do here.")
            raise RuntimeError("Questlog is already running in the game prefix without the capture bridge. "
                               "Quit it (tray icon > Quit) and run this again.")
        server = BridgeServer(log)
        capture = start_dumpcap(dumpcap, interface, address)
        status = {"packets": 0, "error": None}
        threading.Thread(target=pump_records, args=(capture.stdout, server, status), daemon=True).start()
        log(f"Capturing on {interface} ({address}), TCP port {GAME_PORT}.")
        tray = None
        try:
            game_seen = bool(game_processes(APPID, ["aion2.exe"])["aion2.exe"])
            if args.wait_for_game and not game_seen:
                wait_for_game(APPID)
                game_seen = True
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
                if not args.no_auto_update and questlog_update.install_staged(executable.parent, state_dir, log):
                    trial["until"] = time.monotonic() + UPDATE_TRIAL
                log(f"Starting Questlog {questlog_update.installed_version(executable.parent) or '(version unknown)'}.")
                started = launch_questlog(executable, server, address, protontricks, log_path, hidden=hidden)
                tray.start()
                hide_questlog_tray_icon(protontricks, log_path)
                return started

            def start_again():
                return launch_questlog(executable, server, address, protontricks, log_path)

            questlog = start_questlog()
            if not args.no_auto_update:
                threading.Thread(target=check_for_updates, args=(executable.parent, state_dir), daemon=True).start()
            told = False
            game_gone_since = None
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
                    for action in quit_control.handle(request, time.monotonic()):
                        if action == "tray-off":
                            tray.stop()
                        elif action == "tray-on":
                            tray.start()
                        elif action == "close-window":
                            run_ctl_async(protontricks, "close-window", log_path)
                        elif action == "show-window":
                            show_questlog_window(start_again)
                    if request == "quit" and not was_quitting:
                        log(f"Quitting Questlog: hidden now, ended in {SAVE_WAIT} s once it has saved. "
                            "Open it again before then (its menu entry or icon) and it keeps running.")
                    elif request in ("open", "keep") and was_quitting:
                        log("Quit called off: Questlog was asked for again; it keeps running.")
                    elif request == "open":
                        log("Opening Questlog's window (asked from our tray icon or its menu entry).")
                    elif request == "keep":
                        log("The game is being started from Steam; Questlog keeps running.")
                if quit_control.due(time.monotonic()):
                    log("Ending Questlog's session now.")
                    run_ctl(protontricks, "end-session", log_path)
                    wait_for_questlog_exit(f"it had {SAVE_WAIT} s to save")
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
                if status["error"]:
                    raise RuntimeError(status["error"])
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
                elif not game_seen:
                    pass
                elif game_gone_since is None:
                    game_gone_since = time.monotonic()
                    if args.close_with_game:
                        log(f"AION 2 has exited; closing Questlog in {GAME_EXIT_GRACE} s unless the game comes back.")
                    else:
                        log(f"AION 2 has exited. In {GAME_EXIT_GRACE} s Questlog restarts in the background, "
                            "out of the game's Wine session, so that Steam sees the game as closed; it stays "
                            "usable and waits for the next start of the game.")
                elif args.close_with_game and not closing and time.monotonic() - game_gone_since >= GAME_EXIT_GRACE:
                    closing = True
                    tray.stop()
                    close_questlog(prefix, protontricks, log_path)
                elif not args.close_with_game and not quit_control.quitting \
                        and time.monotonic() - game_gone_since >= GAME_EXIT_GRACE:
                    shown = find_questlog_window() is not None
                    log("Moving Questlog out of the game's Wine session; back in a few seconds"
                        + (" with its window open." if shown else ", in the tray."))
                    move_to_fresh_session(prefix, protontricks, log_path)
                    try:
                        questlog.wait(timeout=30)
                    except subprocess.TimeoutExpired:
                        log("The previous Questlog launcher did not end; continuing anyway.")
                    questlog = start_questlog(hidden=not shown)
                    game_seen = False
                    game_gone_since = None
                    told = False
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
            server.stop()
            stop_process(capture)
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
