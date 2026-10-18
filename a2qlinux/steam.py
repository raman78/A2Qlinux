"""Steam launch-option wrapper for AION 2: start A2Qlinux, then the game.

Steam > AION 2 > Properties > General > Launch Options:
    a2qlinux-steam %command%
Launcher options go before %command%, e.g.
    a2qlinux-steam --close-with-game %command%
Questlog unpacked somewhere other than ~/Games/Questlog: put QUESTLOG_DIR=<dir>
in front.

The launcher is started through the user's systemd manager, not as a child of
this process: it then runs with the desktop session's environment instead of
Steam's (overlay preload, container variables), and Steam does not count it as
part of the game. Whatever happens to it, the game is started.
"""

import os
import subprocess
import sys
import time

from .desktop import LOCK, launcher_running

# Launcher options accepted in front of %command%.
OPTIONS = ("--close-with-game", "--no-auto-update")


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
    # Decided before anything is started here: was a launcher (and so possibly
    # a Questlog) already running when Play was pressed?
    launcher_was_running = launcher_running()

    # Questlog starts once the game process is up (--wait-for-game), so the two
    # never bring up the prefix's Wine at the same moment.
    started = subprocess.run(
        ["systemd-run", "--user", "--quiet", "--collect", f"--unit=questlog-aion2-{os.getpid()}",
         sys.executable, "-m", "a2qlinux.desktop", "--wait-for-game", *options],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
    if started.returncode:
        subprocess.run(["notify-send", "--app-name=Questlog (AION 2)", "Questlog (AION 2)",
                        "Could not start Questlog from the Steam launch option; start it from its icon."],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)

    if launcher_was_running:
        args, switched = switch_proton_verb(args)
        if switched:
            with open(LOCK.parent / "steam_launch.log", "a") as record:
                record.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} Questlog launcher running: "
                             "Proton verb waitforexitandrun -> run\n")
    os.execvp(args[0], args)


if __name__ == "__main__":
    sys.exit(main())
