"""a2qlinux-setup: the menu entry for Questlog (AION 2), and a check of what A2Qlinux needs.

    a2qlinux-setup [--questlog-dir DIR] [--desktop-shortcut] [--kde-overlays | --no-kde-overlays]

What it does, in order:
  1. Checks the programs A2Qlinux uses. For the missing ones it prints the
     one command that installs them on this distribution (read from
     /etc/os-release); it never runs sudo itself.
  2. Checks that capturing works, with a one-second capture on `lo` that
     matches nothing, and prints the commands that allow it if not.
  3. Starts the tray icon's check (a2qlinux.tray --check) to see that it can
     run on this desktop.
  4. Checks that the Windows parts are present: shipped in the package, built
     by bridge/build.sh in a source checkout.
  5. Installs the newest Questlog when its folder has no Questlog.exe
     (update.install_fresh: the updater's download and checks).
  6. Takes Questlog's icon from the installed Questlog (resources/icon.png in
     its app.asar) - the icon is Questlog's and is not shipped here.
  7. Writes the menu entry "Questlog (AION 2)" (and, with --desktop-shortcut,
     the same on the desktop), running the `a2qlinux` command.
  8. On KDE Plasma 6, offers the KDE overlays (a2qlinux.kde_overlays): a
     window rule and a script that show Questlog's full-screen overlay layer
     (Black Market Cards) above the game. It explains them and asks, with
     yes as the default; --kde-overlays sets them up without asking,
     --no-kde-overlays removes them. Once set up, a later run refreshes them.
  9. Checks AION 2's Steam launch option (launch_option_step, judged as
     a2qlinux --diagnose does): says when it is set, prints the line to set
     by hand when it is not, and lists it as a problem when it is set so
     that the game cannot start.

Run it again after fixing what it lists, and after moving Questlog's folder.
"""

import argparse
import os
from pathlib import Path
import shutil
import struct
import subprocess
import sys

from . import config, shown_version
from . import kde_overlays
from .desktop import TERMINALS, terminal_command
from .update import install_fresh, read_asar_file

BIN = Path(__file__).resolve().parent / "bin"
ENTRY_ID = "questlog-aion2"
ICON = Path.home() / ".local" / "share" / "icons" / f"{ENTRY_ID}.png"
MENU_ENTRY = Path.home() / ".local" / "share" / "applications" / f"{ENTRY_ID}.desktop"

# program -> the package that provides it, by its name in PACKAGES
NEEDED = {
    "dumpcap": "wireshark",
    "7z": "7zip",
    "protontricks-launch": "protontricks",
    "notify-send": "notify",
    "xdotool": "xdotool",
}
NEEDED_PYTHON = ("PyQt6", "Xlib")      # installed with A2Qlinux by pipx
TRAY_CHECK_WAIT = 30   # s for the tray check to start Qt and answer
CAPTURE_CHECK_WAIT = 15  # s for the one-second capture check

# Package names per distribution family, as in docs/INSTALL.md ("Installing the packages").
PACKAGES = {
    "arch": {"wireshark": "wireshark-cli", "7zip": "7zip", "protontricks": "protontricks",
             "notify": "libnotify", "xdotool": "xdotool", "xcb-cursor": "xcb-util-cursor", "terminal": "xterm"},
    "debian": {"wireshark": "wireshark-common", "7zip": "p7zip-full", "protontricks": "protontricks",
               "notify": "libnotify-bin", "xdotool": "xdotool", "xcb-cursor": "libxcb-cursor0", "terminal": "xterm"},
    "fedora": {"wireshark": "wireshark-cli", "7zip": "7zip", "protontricks": "protontricks",
               "notify": "libnotify", "xdotool": "xdotool", "xcb-cursor": "xcb-util-cursor", "terminal": "xterm"},
    "suse": {"wireshark": "wireshark", "7zip": "7zip", "protontricks": "protontricks",
             "notify": "libnotify-tools", "xdotool": "xdotool", "xcb-cursor": "libxcb-cursor0", "terminal": "xterm"},
}
PACKAGES["ubuntu"] = PACKAGES["debian"]
INSTALLER = {"arch": "sudo pacman -S --needed", "debian": "sudo apt install", "ubuntu": "sudo apt install",
             "fedora": "sudo dnf install", "suse": "sudo zypper install"}


def os_release(path="/etc/os-release"):
    """/etc/os-release as a dict; empty if it cannot be read."""
    info = {}
    try:
        text = Path(path).read_text()
    except OSError:
        return info
    for line in text.splitlines():
        key, sep, value = line.partition("=")
        if sep and key.strip() and not key.startswith("#"):
            info[key.strip()] = value.strip().strip("\"'")
    return info


def distro_family(info):
    """'arch', 'ubuntu', 'debian', 'fedora', 'suse' or None, from ID and ID_LIKE.

    Ubuntu comes before Debian, since Ubuntu and its derivatives (Mint, Pop!_OS)
    name both and differ in where protontricks comes from.
    """
    ids = {info.get("ID", "")} | set(info.get("ID_LIKE", "").split())
    for family, names in (("arch", {"arch"}), ("ubuntu", {"ubuntu"}), ("debian", {"debian"}),
                          ("fedora", {"fedora"}), ("suse", {"suse", "opensuse"})):
        if ids & names:
            return family
    return None


def install_commands(wanted, info):
    """The commands that install the packages named in `wanted` (names from PACKAGES) on this system.

    Unknown distributions get the Arch names and a pointer to the guide,
    which has the table for the others.
    """
    if not wanted:
        return []
    family = distro_family(info)
    if family is None:
        names = " ".join(PACKAGES["arch"][name] for name in wanted)
        return [f"(package names as on Arch; docs/INSTALL.md lists other distributions) {names}"]
    wanted = list(wanted)
    commands = []
    if "protontricks" in wanted and family == "debian" and info.get("VERSION_ID") != "12":
        wanted.remove("protontricks")      # Debian 13 and later have no protontricks package
        commands.append("pipx install protontricks")
    packages = " ".join(PACKAGES[family][name] for name in wanted)
    if packages:
        prefix = "sudo add-apt-repository multiverse && " if family == "ubuntu" and "protontricks" in wanted else ""
        commands.insert(0, f"{prefix}{INSTALLER[family]} {packages}")
    return commands


def installed(program):
    """Path of `program` in PATH, executable by this user or not; None if it is not installed.

    dumpcap is installed root:wireshark 0750 on Arch, Fedora and openSUSE, so
    for a user outside that group shutil.which's executable test misses it;
    that is a missing group membership (capture_problem), not a missing package.
    """
    return shutil.which(program, mode=os.F_OK)


def missing_packages():
    """(missing things to report, package names for install_commands)."""
    missing, wanted = [], []
    for program, package in NEEDED.items():
        if not installed(program):
            missing.append(program)
            wanted.append(package)
    if terminal_command([]) is None:
        missing.append("a terminal for the status window (one of: " + ", ".join(name for name, _ in TERMINALS) + ")")
        wanted.append("terminal")
    if not shutil.which("systemd-run"):
        missing.append("systemd-run (part of systemd; without it the Steam launch option cannot start Questlog)")
    for module in NEEDED_PYTHON:
        if subprocess.run([sys.executable, "-c", f"import {module}"], capture_output=True).returncode:
            missing.append(f"the Python module {module}, which comes with A2Qlinux: run pipx reinstall a2qlinux")
    return missing, wanted


def _has_capture_rights(path):
    """True if dumpcap carries file capabilities or the setuid bit (what lets the group capture)."""
    try:
        os.getxattr(path, "security.capability")
        return True
    except OSError:
        return bool(os.stat(path).st_mode & 0o4000)


def capture_problem(info):
    """Why capturing does not work yet, with the commands that fix it; None if it works.

    Capturing is tried for real: one second on `lo` with a filter nothing
    matches, written nowhere. Listing devices (dumpcap -D) is no check: it
    works without any capture rights.
    """
    dumpcap = installed("dumpcap")
    if not dumpcap:
        return None                        # reported with the missing packages
    try:
        if not os.access(dumpcap, os.X_OK):
            raise PermissionError(f"dumpcap: only members of the 'wireshark' group may run {dumpcap}")
        done = subprocess.run([dumpcap, "-i", "lo", "-f", "tcp port 1", "-a", "duration:1", "-q", "-w", "-"],
                              stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
                              text=True, timeout=CAPTURE_CHECK_WAIT)
    except subprocess.TimeoutExpired:
        return f"the capture check did not end within {CAPTURE_CHECK_WAIT} s"
    except PermissionError as error:
        reason = str(error)
    else:
        if done.returncode == 0:
            return None
        reason = next((line.strip() for line in done.stderr.splitlines() if line.startswith("dumpcap:")),
                      f"dumpcap ended with code {done.returncode}")
    steps = []
    if os.access(dumpcap, os.X_OK) and not _has_capture_rights(os.path.realpath(dumpcap)):
        if distro_family(info) in ("debian", "ubuntu"):
            steps.append("sudo dpkg-reconfigure wireshark-common      (answer Yes)")
        else:
            steps.append(f"{dumpcap} has no capture capabilities; reinstall the Wireshark package")
    user = os.environ.get("USER") or subprocess.run(["id", "-un"], capture_output=True, text=True).stdout.strip()
    session = subprocess.run(["id", "-nG"], capture_output=True, text=True).stdout.split()
    configured = subprocess.run(["id", "-nG", user], capture_output=True, text=True).stdout.split()
    if "wireshark" not in configured:
        steps.append("sudo usermod -aG wireshark $USER")
    if "wireshark" not in session or "wireshark" not in configured:
        steps.append("then log out of the desktop and log in again (the group is read at login)")
    return ("capturing is not allowed yet (" + reason + ")"
            + "".join(f"\n      {step}" for step in steps))


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


def launch_option_step(steam_command, accounts=None, say=print):
    """Say whether AION 2's Steam launch option is set, as a2qlinux --diagnose judges it; problems found.

    Optional, so not being set is no problem; set in a way that keeps the
    game from starting (no %command%, a path that is gone) is one.
    """
    from .diagnose import OK, PROBLEM, judge_launch_option, launch_options
    from .launcher import APPID, steam_roots
    accounts = launch_options(steam_roots(), APPID) if accounts is None else accounts
    line = f"    {steam_command} %command%"
    if not accounts:
        say("\nSteam > AION 2 > Properties > General > Launch Options (optional, starts Questlog with the game):")
        say(line)
        return []
    problems = []
    for account, option in accounts:
        level, text = judge_launch_option(option, steam_command)
        label = "Steam launch option" + (f" (account {account.name})" if len(accounts) > 1 else "")
        if level == OK:
            say(f"{label}: set ({option}).")
        elif level == PROBLEM:
            problems.append(f"{label}: {text}")
        else:
            say(f"\n{label}: {text}")
    if any(level != OK for level, _ in (judge_launch_option(o, steam_command) for _, o in accounts)):
        say("Steam > AION 2 > Properties > General > Launch Options (optional, starts Questlog with the game):")
        say(line)
    return problems


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--questlog-dir", type=Path,
                        default=None,
                        help=f"Questlog's folder (default: from {config.CONFIG_PATH}, else ~/Games/Questlog); "
                             "written into the settings file. Without Questlog.exe in it, the newest Questlog "
                             "is installed there")
    parser.add_argument("--desktop-shortcut", action="store_true", help="also put the entry on the desktop")
    kde = parser.add_mutually_exclusive_group()
    kde.add_argument("--kde-overlays", dest="kde_overlays", action="store_const", const=True, default=None,
                     help="KDE Plasma 6: show Questlog's full-screen overlays (Black Market Cards) above the "
                          "game, without asking")
    kde.add_argument("--no-kde-overlays", dest="kde_overlays", action="store_const", const=False,
                     help="remove what --kde-overlays set up")
    parser.add_argument("--version", action="version", version=f"A2Qlinux {shown_version()}")
    args = parser.parse_args()
    created = not config.CONFIG_PATH.exists()
    if args.questlog_dir:
        # Into the settings file, which every A2Qlinux command reads, so the
        # folder used here is the one the launcher uses later.
        config.set_questlog_dir(args.questlog_dir.expanduser().resolve())
    elif created:
        config.CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
        config.CONFIG_PATH.write_text(config.template())
    settings, config_problems = config.load()
    questlog_dir = settings.questlog_dir.resolve()
    problems = list(config_problems)
    print(f"Settings: {config.CONFIG_PATH}"
          + (" (every setting at its default, with comments)" if created else "")
          + (f"; questlog_dir = {questlog_dir}" if args.questlog_dir else ""))
    if os.environ.get("QUESTLOG_DIR"):
        print(f"Note: the QUESTLOG_DIR environment variable sets Questlog's folder to {questlog_dir}, over "
              f"{config.CONFIG_PATH}; the menu entry and Steam do not see that variable.")

    info = os_release()
    missing, wanted = missing_packages()
    tray = tray_problem()
    if tray and "xcb-cursor" in tray:
        wanted.append("xcb-cursor")
    commands = install_commands(wanted, info)
    if missing or commands:
        problems.append("missing: " + "; ".join(missing or ["a library for the tray icon"])
                        + "".join(f"\n      {line}" for line in commands))
    capture = capture_problem(info)
    if capture:
        problems.append(capture)
    if tray:
        problems.append(tray)

    parts_problem = windows_parts_problem()
    if parts_problem:
        problems.append(parts_problem)

    asar = questlog_dir / "resources" / "app.asar"
    if not (questlog_dir / "Questlog.exe").is_file():
        if not shutil.which("7z"):
            problems.append(f"Questlog is not in {questlog_dir} yet; it is installed there once 7z is installed "
                            "(see 'missing' above)")
        else:
            print(f"Questlog is not in {questlog_dir}; installing the newest version there. To use a Questlog "
                  "you already have instead, stop with Ctrl+C and pass its folder with --questlog-dir.")
            try:
                install_fresh(questlog_dir, print)
            except RuntimeError as error:
                problems.append(str(error))
    if (questlog_dir / "Questlog.exe").is_file():
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

    # A note, not a problem: everything else works without the KDE overlays.
    kde_problem = kde_overlays.setup_step(args.kde_overlays, input, sys.stdin.isatty())
    if kde_problem:
        print(f"Note: {kde_problem}.", file=sys.stderr)

    problems += launch_option_step(command("a2qlinux-steam"))

    if problems:
        print("\nNot ready yet. Fix these, then run a2qlinux-setup again:", file=sys.stderr)
        for problem in problems:
            print(f"  - {problem}", file=sys.stderr)
        return 1
    print("\nReady. Start 'Questlog (AION 2)' from the menu.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
