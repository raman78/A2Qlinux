"""a2qlinux-setup: the menu entry for Questlog (AION 2), and a check of what A2Qlinux needs.

    a2qlinux-setup [--questlog-dir DIR] [--desktop-shortcut]

What it does, in order:
  1. Checks the programs A2Qlinux uses and names the missing ones; installs nothing.
     Starts the tray icon's check (a2qlinux.tray --check) to see that it can
     run on this desktop.
  2. Checks that the Windows parts are present: shipped in the package, built
     by bridge/build.sh in a source checkout.
  3. Takes Questlog's icon from the installed Questlog (resources/icon.png in
     its app.asar) - the icon is Questlog's and is not shipped here.
  4. Writes the menu entry "Questlog (AION 2)" (and, with --desktop-shortcut,
     the same on the desktop), running the `a2qlinux` command.
  5. Prints the Steam launch option to set by hand.

Run it again after moving Questlog's folder.
"""

import argparse
import os
from pathlib import Path
import shutil
import struct
import subprocess
import sys

from . import config
from .desktop import TERMINALS, terminal_command
from .update import read_asar_file

BIN = Path(__file__).resolve().parent / "bin"
ENTRY_ID = "questlog-aion2"
ICON = Path.home() / ".local" / "share" / "icons" / f"{ENTRY_ID}.png"
MENU_ENTRY = Path.home() / ".local" / "share" / "applications" / f"{ENTRY_ID}.desktop"

# program -> what provides it (Arch / CachyOS package; other distributions: docs/INSTALL.md)
NEEDED = {
    "dumpcap": "wireshark-cli (and membership of the 'wireshark' group)",
    "7z": "7zip (unpacks Questlog's installer for updates)",
    "protontricks-launch": "protontricks",
    "notify-send": "libnotify",
    "xdotool": "xdotool",
    "systemd-run": "systemd",
}
NEEDED_PYTHON = {"PyQt6": "python-pyqt6", "Xlib": "python-xlib"}
TRAY_CHECK_WAIT = 30   # s for the tray check to start Qt and answer


def check_programs():
    missing = [f"{program} ({package})" for program, package in NEEDED.items() if not shutil.which(program)]
    if terminal_command([]) is None:
        missing.append("a terminal for the status window (one of: "
                       + ", ".join(name for name, _ in TERMINALS) + ")")
    for module, package in NEEDED_PYTHON.items():
        if subprocess.run([sys.executable, "-c", f"import {module}"], capture_output=True).returncode:
            missing.append(f"Python module {module} ({package})")
    groups = subprocess.run(["id", "-nG"], capture_output=True, text=True).stdout.split()
    if "wireshark" not in groups:
        missing.append("membership of the 'wireshark' group: sudo usermod -aG wireshark $USER, then log in again")
    return missing


def tray_problem():
    """Why A2Qlinux's tray icon could not run on this desktop; None if it can.

    Runs the tray itself (a2qlinux.tray --check), so what is checked is what
    the launcher will start: Qt with the desktop's display, and a system tray.
    """
    if not (os.environ.get("WAYLAND_DISPLAY") or os.environ.get("DISPLAY")):
        return "the tray icon could not be checked: no desktop session here (run a2qlinux-setup on the desktop)"
    try:
        # Qt logs to the journal, not to a stderr that is not a terminal, unless told to.
        done = subprocess.run([sys.executable, "-m", "a2qlinux.tray", "--check"], stdin=subprocess.DEVNULL,
                              capture_output=True, text=True, timeout=TRAY_CHECK_WAIT,
                              env={**os.environ, "QT_FORCE_STDERR_LOGGING": "1"})
    except subprocess.TimeoutExpired:
        return f"the tray icon check did not answer within {TRAY_CHECK_WAIT} s"
    if done.returncode == 0:
        return None
    lines = [line.strip() for line in done.stderr.splitlines() if line.strip()]
    # Qt names a missing library in its qt.qpa lines, above its closing summary.
    reason = " / ".join([line for line in lines if line.startswith(("qt.qpa", "a2qlinux tray:"))]
                        or lines[-3:]) or f"exit code {done.returncode}"
    return (f"A2Qlinux's tray icon cannot run here ({reason}); "
            "see 'The tray icon' in docs/TROUBLESHOOTING.md")


def windows_parts_problem():
    missing = [name for name in ("wpcap.dll", "questlog_ctl.exe") if not (BIN / name).is_file()]
    if missing:
        return (f"{', '.join(missing)} missing from {BIN}; in a source checkout run: bash bridge/build.sh "
                "(needs clang, lld and wine)")
    return None


def command(name):
    """Absolute path of one of A2Qlinux's commands, as installed with this Python.

    pipx links the commands into ~/.local/bin and keeps them in the
    environment's bin folder; either works, the first is stable across upgrades.
    """
    found = shutil.which(name)
    if found:
        return found
    beside = Path(sys.executable).parent / name
    if beside.is_file():
        return str(beside)
    raise RuntimeError(f"the command {name} is not installed; install A2Qlinux with pipx first")


def desktop_entry(questlog_dir):
    run = command("a2qlinux")      # where Questlog is comes from the settings file
    return ("[Desktop Entry]\n"
            "Type=Application\n"
            "Name=Questlog (AION 2)\n"
            "Comment=Questlog Desktop for AION 2 under Proton, fed with live game traffic\n"
            f"Exec={run}\n"
            f"Icon={ICON}\n"
            "Terminal=false\n"
            "Categories=Game;\n")


def desktop_shortcut_path():
    folder = subprocess.run(["xdg-user-dir", "DESKTOP"], capture_output=True, text=True).stdout.strip()
    return Path(folder or Path.home() / "Desktop") / f"{ENTRY_ID}.desktop"


def entry_command(path):
    """The program an existing entry runs (after any `env VAR=…`), or None."""
    try:
        text = Path(path).read_text()
    except OSError:
        return None
    for line in text.splitlines():
        if line.startswith("Exec="):
            words = line[len("Exec="):].split()
            if words and words[0] == "env":
                words = [w for w in words[1:] if "=" not in w]
            return words[0] if words else None
    return None


def refresh_entries(log=lambda text: None):
    """Keep the menu entry (and an existing desktop shortcut) pointing at this installation.

    Run on every start of `a2qlinux`, like sto-clare does for its own entry.
    An entry whose command is this installation's `a2qlinux` is left alone,
    with any options added to it by hand; any other - missing, from an older
    layout (python3 …/questlog_desktop.py), or from an installation that was
    moved or removed - is written again. The desktop shortcut is only
    rewritten if it exists. Returns the paths written.
    """
    ours = command("a2qlinux")
    questlog_dir = config.questlog_dir().resolve()
    written = []
    for path, create in ((MENU_ENTRY, True), (desktop_shortcut_path(), False)):
        if not path.exists() and not create:
            continue
        if entry_command(path) == ours:
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(desktop_entry(questlog_dir))
        if path != MENU_ENTRY:
            path.chmod(0o755)
        log(f"Rewrote {path}: it did not run this installation's a2qlinux.")
        written.append(path)
    if not ICON.exists():
        try:
            ICON.parent.mkdir(parents=True, exist_ok=True)
            ICON.write_bytes(read_asar_file(questlog_dir / "resources" / "app.asar", "resources/icon.png"))
        except (OSError, KeyError, ValueError, struct.error):
            pass                  # the entry works without its icon; a2qlinux-setup reports why
    return written


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--questlog-dir", type=Path,
                        default=None,
                        help=f"folder with Questlog.exe (default: from {config.CONFIG_PATH}, else ~/Games/Questlog); "
                             "written into a new settings file")
    parser.add_argument("--desktop-shortcut", action="store_true", help="also put the entry on the desktop")
    args = parser.parse_args()
    settings, config_problems = config.load()
    questlog_dir = (args.questlog_dir or settings.questlog_dir).expanduser().resolve()
    problems = list(config_problems)
    if not config.CONFIG_PATH.exists():
        config.CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
        config.CONFIG_PATH.write_text(config.template(questlog_dir))
        print(f"Settings: {config.CONFIG_PATH} (every setting at its default, with comments)")
    elif questlog_dir != settings.questlog_dir.resolve():
        problems.append(f"--questlog-dir {questlog_dir} differs from {settings.questlog_dir} in "
                        f"{config.CONFIG_PATH}; set questlog_dir there, which A2Qlinux reads")
    else:
        print(f"Settings: {config.CONFIG_PATH}")

    missing = check_programs()
    if missing:
        problems.append("missing: " + "; ".join(missing))
    tray = tray_problem()
    if tray:
        problems.append(tray)

    parts_problem = windows_parts_problem()
    if parts_problem:
        problems.append(parts_problem)

    asar = questlog_dir / "resources" / "app.asar"
    if not (questlog_dir / "Questlog.exe").is_file():
        problems.append(f"Questlog.exe not found in {questlog_dir}; unpack Questlog there "
                        "(docs/INSTALL.md, 'Installing Questlog') or pass --questlog-dir")
    else:
        try:
            icon = read_asar_file(asar, "resources/icon.png")
            ICON.parent.mkdir(parents=True, exist_ok=True)
            ICON.write_bytes(icon)
            print(f"Icon: {ICON}")
        except (OSError, KeyError, ValueError, struct.error) as error:
            problems.append(f"could not take Questlog's icon from {asar}: {error!r}")

    try:
        entry = desktop_entry(questlog_dir)
    except RuntimeError as error:
        print(f"a2qlinux-setup: {error}", file=sys.stderr)
        return 1
    MENU_ENTRY.parent.mkdir(parents=True, exist_ok=True)
    MENU_ENTRY.write_text(entry)
    print(f"Menu entry: {MENU_ENTRY}")
    if args.desktop_shortcut:
        shortcut = desktop_shortcut_path()
        shortcut.write_text(entry)
        shortcut.chmod(0o755)
        print(f"Desktop shortcut: {shortcut}")

    print("\nSteam > AION 2 > Properties > General > Launch Options (optional, starts Questlog with the game):")
    print(f"    {command('a2qlinux-steam')} %command%")

    if problems:
        print("\nNot ready yet:", file=sys.stderr)
        for problem in problems:
            print(f"  - {problem}", file=sys.stderr)
        return 1
    print("\nReady. Start 'Questlog (AION 2)' from the menu.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
