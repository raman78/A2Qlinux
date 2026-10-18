#!/usr/bin/env python3
"""Install A2Qlinux's desktop entry for Questlog (AION 2) and check what it needs.

    python3 install.py [--questlog-dir DIR] [--desktop-shortcut]

What it does, in order:
  1. Checks the programs A2Qlinux uses and names the missing ones; installs nothing.
  2. Builds the Windows parts (bridge/build.sh) if they are not built yet.
  3. Takes Questlog's icon from the installed Questlog (resources/icon.png in
     its app.asar) - the icon is Questlog's and is not shipped here.
  4. Writes the menu entry "Questlog (AION 2)" (and, with --desktop-shortcut,
     the same on the desktop), pointing at this checkout.
  5. Prints the Steam launch option to set by hand.

Run it again after moving this checkout or Questlog's folder.
"""

import argparse
import json
import os
from pathlib import Path
import shutil
import struct
import subprocess
import sys

HERE = Path(__file__).resolve().parent
DEFAULT_QUESTLOG_DIR = Path.home() / "Games" / "Questlog"
ENTRY_ID = "questlog-aion2"
ICON = Path.home() / ".local" / "share" / "icons" / f"{ENTRY_ID}.png"
MENU_ENTRY = Path.home() / ".local" / "share" / "applications" / f"{ENTRY_ID}.desktop"

# program -> what provides it (Arch / CachyOS package)
NEEDED = {
    "dumpcap": "wireshark-cli (and membership of the 'wireshark' group)",
    "protontricks-launch": "protontricks",
    "konsole": "konsole",
    "notify-send": "libnotify",
    "xdotool": "xdotool",
    "systemd-run": "systemd",
}
NEEDED_PYTHON = {"PyQt6": "python-pyqt6", "Xlib": "python-xlib"}
NEEDED_TO_BUILD = {"clang": "clang", "ld.lld": "lld"}


def read_asar_file(asar, name):
    """One file from an Electron app.asar archive.

    Layout: a 16-byte prefix (pickle sizes; the 4th field is the length of
    the JSON header), the JSON header describing every file with an offset
    relative to the end of the header pickle, then the file data. Files kept
    outside the archive are in app.asar.unpacked.
    """
    with open(asar, "rb") as stream:
        _, header_size, _, json_size = struct.unpack("<4I", stream.read(16))
        node = json.loads(stream.read(json_size))
        for part in name.split("/"):
            node = node["files"][part]
        if node.get("unpacked"):
            return (Path(str(asar) + ".unpacked") / name).read_bytes()
        stream.seek(8 + header_size + int(node["offset"]))
        return stream.read(node["size"])


def check_programs():
    missing = [f"{program} ({package})" for program, package in NEEDED.items() if not shutil.which(program)]
    for module, package in NEEDED_PYTHON.items():
        if subprocess.run([sys.executable, "-c", f"import {module}"], capture_output=True).returncode:
            missing.append(f"Python module {module} ({package})")
    groups = subprocess.run(["id", "-nG"], capture_output=True, text=True).stdout.split()
    if "wireshark" not in groups:
        missing.append("membership of the 'wireshark' group: sudo usermod -aG wireshark $USER, then log in again")
    return missing


def build_windows_parts():
    built = [HERE / "bridge" / "wpcap.dll", HERE / "bridge" / "questlog_ctl.exe"]
    if all(path.is_file() for path in built):
        return None
    missing = [f"{program} ({package})" for program, package in NEEDED_TO_BUILD.items() if not shutil.which(program)]
    if not Path("/usr/include/wine/windows/windows.h").is_file():
        missing.append("Wine's headers (wine)")
    if missing:
        return "cannot build the Windows parts, missing: " + ", ".join(missing)
    result = subprocess.run(["bash", str(HERE / "bridge" / "build.sh")], capture_output=True, text=True)
    if result.returncode:
        return "bridge/build.sh failed:\n" + result.stdout + result.stderr
    return None


def desktop_entry(questlog_dir):
    command = f"python3 {HERE / 'questlog_desktop.py'}"
    if questlog_dir != DEFAULT_QUESTLOG_DIR:
        command = f"env QUESTLOG_DIR={questlog_dir} {command}"
    return ("[Desktop Entry]\n"
            "Type=Application\n"
            "Name=Questlog (AION 2)\n"
            "Comment=Questlog Desktop for AION 2 under Proton, fed with live game traffic\n"
            f"Exec={command}\n"
            f"Icon={ICON}\n"
            "Terminal=false\n"
            "Categories=Game;\n")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--questlog-dir", type=Path,
                        default=Path(os.environ.get("QUESTLOG_DIR") or DEFAULT_QUESTLOG_DIR),
                        help=f"folder with Questlog.exe (default {DEFAULT_QUESTLOG_DIR})")
    parser.add_argument("--desktop-shortcut", action="store_true", help="also put the entry on the desktop")
    args = parser.parse_args()
    questlog_dir = args.questlog_dir.expanduser().resolve()
    problems = []

    missing = check_programs()
    if missing:
        problems.append("missing: " + "; ".join(missing))

    build_problem = build_windows_parts()
    if build_problem:
        problems.append(build_problem)

    asar = questlog_dir / "resources" / "app.asar"
    if not (questlog_dir / "Questlog.exe").is_file():
        problems.append(f"Questlog.exe not found in {questlog_dir}; unpack Questlog there "
                        "(docs/MANUAL.md, 'Installing Questlog') or pass --questlog-dir")
    else:
        try:
            icon = read_asar_file(asar, "resources/icon.png")
            ICON.parent.mkdir(parents=True, exist_ok=True)
            ICON.write_bytes(icon)
            print(f"Icon: {ICON}")
        except (OSError, KeyError, ValueError, struct.error) as error:
            problems.append(f"could not take Questlog's icon from {asar}: {error!r}")

    entry = desktop_entry(questlog_dir)
    MENU_ENTRY.parent.mkdir(parents=True, exist_ok=True)
    MENU_ENTRY.write_text(entry)
    print(f"Menu entry: {MENU_ENTRY}")
    if args.desktop_shortcut:
        desktop = Path(subprocess.run(["xdg-user-dir", "DESKTOP"], capture_output=True, text=True).stdout.strip()
                       or Path.home() / "Desktop")
        shortcut = desktop / f"{ENTRY_ID}.desktop"
        shortcut.write_text(entry)
        shortcut.chmod(0o755)
        print(f"Desktop shortcut: {shortcut}")

    prefix = "" if questlog_dir == DEFAULT_QUESTLOG_DIR else f"QUESTLOG_DIR={questlog_dir} "
    print("\nSteam > AION 2 > Properties > General > Launch Options (optional, starts Questlog with the game):")
    print(f"    {prefix}{HERE / 'steam_launch.sh'} %command%")

    if problems:
        print("\nNot ready yet:", file=sys.stderr)
        for problem in problems:
            print(f"  - {problem}", file=sys.stderr)
        return 1
    print("\nReady. Start 'Questlog (AION 2)' from the menu.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
