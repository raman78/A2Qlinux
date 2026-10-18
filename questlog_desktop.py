#!/usr/bin/env python3
"""Desktop and menu entry point: open questlog_start.py in a terminal, once.

Arguments are passed on to questlog_start.py, e.g. --close-with-game.

If questlog_start.py is already running (its lock is held), no second one is
started; the running one is asked instead, by a signal to the PID in its lock
file:
  - from the icon or menu: SIGUSR1, "open Questlog's window" - which also calls
    off a quit chosen in our tray icon a moment before;
  - from the Steam launch option (--wait-for-game; the game is starting):
    SIGUSR2, "keep Questlog running" - calls off such a quit, opens nothing.
If the launcher was just ending, it lets go of the lock instead of answering;
a new one is then started here.
"""

import fcntl
import os
from pathlib import Path
import signal
import subprocess
import sys
import time

HERE = Path(__file__).resolve().parent
QUESTLOG_DIR = Path(os.environ.get("QUESTLOG_DIR") or Path.home() / "Games" / "Questlog").expanduser()
LOCK = QUESTLOG_DIR / "proton-stream" / ".lock"


def launcher_running():
    """True if questlog_start.py holds its lock right now."""
    try:
        fd = os.open(LOCK, os.O_RDWR | os.O_CLOEXEC)
    except FileNotFoundError:
        return False
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        return True
    finally:
        os.close(fd)
    return False


HANDOVER_WAIT = 10   # s for a launcher that was ending to let go of its lock


def launcher_pid():
    """PID of the running questlog_start.py, from its lock file; None if it cannot be told.

    Checked against the process's command line, so a stale or reused PID is
    never signalled.
    """
    try:
        pid = int(LOCK.read_text().strip())
        command = Path(f"/proc/{pid}/cmdline").read_bytes().split(b"\0")
    except (OSError, ValueError):
        return None
    return pid if any(arg.endswith(b"questlog_start.py") for arg in command) else None


def ask_running_launcher(game_starting):
    """Signal the running launcher. True if it answers, False if it has just ended."""
    pid = launcher_pid()
    if pid is None:
        notify("Already running - use its open terminal window.")
        return True
    try:
        os.kill(pid, signal.SIGUSR2 if game_starting else signal.SIGUSR1)
    except ProcessLookupError:
        pass
    deadline = time.monotonic() + HANDOVER_WAIT
    while time.monotonic() < deadline:
        if not launcher_running():
            return False
        time.sleep(0.2)
    return True


def notify(text):
    subprocess.run(["notify-send", "--app-name=Questlog (AION 2)",
                    "--icon=" + str(Path.home() / ".local/share/icons/questlog-aion2.png"),
                    "Questlog (AION 2)", text], check=False)


def main():
    if launcher_running() and ask_running_launcher("--wait-for-game" in sys.argv[1:]):
        return 0
    # The window closes by itself when the launcher ends normally (Questlog
    # closed after the game); on an error it stays open until Enter, so the
    # message can be read.
    # Any arguments (e.g. --close-with-game) are passed on to questlog_start.py.
    script = ('"$0" "$@"; code=$?; if [ $code -ne 0 ]; then echo; '
              'read -rp "questlog_start.py ended with code $code - press Enter to close. "; fi')
    os.execvp("konsole", ["konsole", "-e", "bash", "-c", script, sys.executable,
                          str(HERE / "questlog_start.py"), *sys.argv[1:]])


if __name__ == "__main__":
    sys.exit(main())
