"""Steam launch-option wrapper for AION 2: start A2Qlinux, then the game.

Steam > AION 2 > Properties > General > Launch Options:
    a2qlinux-steam %command%
Launcher options go before %command%, e.g.
    a2qlinux-steam --close-with-game %command%
Where Questlog is, and what happens after the game, come from
~/.config/a2qlinux/config.toml (a2qlinux.config).

The launcher is started through the user's systemd manager, not as a child of
this process: it then runs with the desktop session's environment instead of
Steam's (overlay preload, container variables), and Steam does not count it as
part of the game. Whatever happens to it, the game is started.

The game starts once Questlog runs, and joins Questlog's Wine session. The
session then belongs to Questlog's launch, not to the game's, so when the game
ends, Steam can be told so without touching Questlog (docs/ARCHITECTURE.md
§5.1, §6.7).
"""

import os
import subprocess
import sys
import time

from .desktop import LOCK
from .launcher import APPID, game_processes

# Launcher options accepted in front of %command%.
OPTIONS = ("--close-with-game", "--no-auto-update")
QUESTLOG_UP_WAIT = 60   # s for Questlog to be running before the game starts without it


def wait_for_questlog(timeout=QUESTLOG_UP_WAIT):
    """True once Questlog runs in the game's prefix, False if it does not within `timeout` s."""
    deadline = time.monotonic() + timeout
    while not game_processes(APPID, ["questlog.exe"])["questlog.exe"]:
        if time.monotonic() >= deadline:
            return False
        time.sleep(0.25)
    return True


def record(text):
    with open(LOCK.parent / "steam_launch.log", "a") as log:
        log.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} {text}\n")


def switch_proton_verb(command):
    """Proton's `waitforexitandrun` -> `run`; returns (command, switched).

    Questlog may already run in the game's prefix (started from its icon, e.g.
    to look through saved fights). Proton's waitforexitandrun would then wait
    for the prefix to go idle - i.e. until Questlog is closed. With `run`, the
    game joins the Wine session Questlog runs in, and Questlog sees it at once.
    Only Proton's own verb is switched: the word right after a `…/proton`
    argument. Steam's runtime keeps --verb=waitforexitandrun, which marks the
    game's main container.
    """
    command = list(command)
    for i in range(1, len(command)):
        if command[i] == "waitforexitandrun" and command[i - 1].endswith("/proton"):
            command[i] = "run"
            return command, True
    return command, False


def main():
    args = sys.argv[1:]
    options = []
    while args and args[0] in OPTIONS:
        options.append(args.pop(0))
    if not args:
        print("usage: a2qlinux-steam [--close-with-game] [--no-auto-update] %command%", file=sys.stderr)
        return 2
    started = subprocess.run(
        ["systemd-run", "--user", "--quiet", "--collect", f"--unit=questlog-aion2-{os.getpid()}",
         sys.executable, "-m", "a2qlinux.desktop", "--for-game", *options],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
    if started.returncode:
        subprocess.run(["notify-send", "--app-name=Questlog (AION 2)", "Questlog (AION 2)",
                        "Could not start Questlog from the Steam launch option; start it from its icon."],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)

    # The game waits for Questlog, then joins its Wine session (`run`); the two
    # never bring up the prefix's Wine at the same moment. Without Questlog the
    # game starts as Steam asked; a Questlog that comes up later yields to it
    # (the launcher's steam_launch_pending).
    # (A Questlog already running is joined even if starting the launcher failed.)
    if wait_for_questlog(QUESTLOG_UP_WAIT if not started.returncode else 0):
        args, switched = switch_proton_verb(args)
        if switched:
            record("Questlog running: Proton verb waitforexitandrun -> run")
    elif not started.returncode:
        record(f"Questlog not running {QUESTLOG_UP_WAIT} s after the launcher was started; "
               "the game starts on its own")
    os.execvp(args[0], args)


if __name__ == "__main__":
    sys.exit(main())
