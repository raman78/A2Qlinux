#!/usr/bin/env python3
"""Desktop and menu entry point: open the launcher (a2qlinux.launcher) in a terminal, once.

Arguments are passed on to the launcher (a2qlinux.launcher), e.g. --close-with-game.

If the launcher (a2qlinux.launcher) is already running (its lock is held), no second one is
started; the running one is asked instead, by a signal to the PID in its lock
file:
  - from the icon or menu: SIGUSR1, "open Questlog's window" - which also calls
    off a quit chosen in our tray icon a moment before;
  - from the Steam launch option (--for-game; the game is starting):
    SIGUSR2, "keep Questlog running" - calls off such a quit, opens nothing.
If the launcher was just ending, it lets go of the lock instead of answering;
a new one is then started here.
"""

import fcntl
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import time

from .config import questlog_dir

LOCK = questlog_dir() / "proton-stream" / ".lock"

# Terminals the status window can open in, first found wins, each with the
# option after which it takes a program and its arguments as separate words
# (from each one's manual). x-terminal-emulator is Debian's alternative for
# whichever terminal is installed; Debian policy requires it to take -e so.
TERMINALS = (
    ("konsole", ["-e"]),
    ("gnome-terminal", ["--"]),
    ("ptyxis", ["--"]),
    ("xfce4-terminal", ["-x"]),
    ("mate-terminal", ["-x"]),
    ("x-terminal-emulator", ["-e"]),
    ("xterm", ["-e"]),
)


def terminal_command(program, which=shutil.which):
    """The command that runs `program` (a list of words) in a new terminal window; None without a terminal."""
    for name, option in TERMINALS:
        found = which(name)
        if found:
            return [found, *option, *program]
    return None


def launcher_running():
    """True if the launcher (a2qlinux.launcher) holds its lock right now."""
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
    """PID of the running the launcher (a2qlinux.launcher), from its lock file; None if it cannot be told.

    Checked against the process's command line, so a stale or reused PID is
    never signalled.
    """
    try:
        pid = int(LOCK.read_text().strip())
        command = Path(f"/proc/{pid}/cmdline").read_bytes().split(b"\0")
    except (OSError, ValueError):
        return None
    return pid if b"a2qlinux.launcher" in command else None


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
    if "--version" in sys.argv[1:]:          # answered here: passed on, it would open a terminal window
        from . import shown_version
        print(f"A2Qlinux {shown_version()}")
        return 0
    try:
        from .setup_desktop import refresh_entries
        refresh_entries(lambda text: print(f"a2qlinux: {text}", file=sys.stderr))
    except (OSError, RuntimeError) as error:   # never in the way of starting Questlog
        print(f"a2qlinux: could not check the menu entry: {error}", file=sys.stderr)
    # --for-game only tells who is asking; the launcher starts Questlog at once either way.
    for_game = "--for-game" in sys.argv[1:]
    options = [arg for arg in sys.argv[1:] if arg != "--for-game"]
    if launcher_running() and ask_running_launcher(for_game):
        return 0
    # The window closes by itself when the launcher ends normally (Questlog
    # closed after the game); on an error it stays open until Enter, so the
    # message can be read.
    # Any arguments (e.g. --close-with-game) are passed on to the launcher (a2qlinux.launcher).
    script = ('"$0" "$@"; code=$?; if [ $code -ne 0 ]; then echo; '
              'read -rp "A2Qlinux ended with code $code - press Enter to close. "; fi')
    command = terminal_command(["bash", "-c", script, sys.executable, "-m", "a2qlinux.launcher", *options])
    if command is None:
        message = ("No terminal for the status window was found. Install one of: "
                   + ", ".join(name for name, _ in TERMINALS) + ".")
        print(f"a2qlinux: {message}", file=sys.stderr)
        notify(message)
        return 1
    os.execv(command[0], command)


if __name__ == "__main__":
    sys.exit(main())
