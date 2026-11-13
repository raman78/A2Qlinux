"""Questlog's "Open Folder" buttons: a handler for opening folders in the game's prefix (docs/ARCHITECTURE.md §6.10).

Questlog opens a folder (Combat Meter > Recordings > Open Folder) with
Electron's shell.openPath, which asks Windows for the verb "explore" of the
class "folder". Wine's prefix has no command for that verb, so Wine shows
"There is no Windows program configured to open this type of file" instead.

a2qlinux-setup offers to add the one missing command,
HKLM\\Software\\Classes\\folder\\shell\\explore\\command, set to Wine's
winebrowser.exe - what the prefix already uses for web links - which hands
the folder to xdg-open, so it opens in the desktop's file manager. The
registry is read and written by questlog_ctl.exe (`folder-handler`) inside
the prefix, so the live registry is what is checked, also while the game
runs. A command that someone else put there is never changed or removed.
`a2qlinux --diagnose` only reads: it looks the key up in the prefix's
system.reg (registry_state) and starts no Wine.
"""

from pathlib import Path
import re
import shutil
import subprocess

APPID = 3393110
CTL_WAIT = 120          # s for protontricks-launch to start Wine and questlog_ctl.exe to answer
HANDLER_KEY = r"Software\\Classes\\folder\\shell\\explore\\command"   # as system.reg spells it
HANDLER_VALUE = r'"C:\windows\system32\winebrowser.exe" "%1"'           # what questlog_ctl.exe writes
OUTCOMES = ("absent", "ours", "other", "set", "removed", "error")

EXPLANATION = """\
Questlog's "Open Folder" buttons (for example under Combat Meter > Recordings)
need a program that opens folders, and AION 2's Wine prefix has none for them,
so Questlog shows "There is no Windows program configured to open this type of
file". A2Qlinux can add that one missing entry to the prefix's registry; the
folder then opens in your desktop's file manager. Nothing that works already
changes; `a2qlinux-setup --no-open-folders` removes the entry again."""


def registry_state(system_reg):
    """("absent" | "ours" | "other", value or None) from the prefix's system.reg, read as text.

    The same three answers as questlog_ctl.exe folder-handler status. The
    file is the wineserver's last save: it saves a change about 30 s later
    (26 s measured), so a change made just now may not be in it yet.
    """
    text = Path(system_reg).read_text(encoding="utf-8", errors="replace")
    section = re.search(r"^\[" + re.escape(HANDLER_KEY) + r"\][^\n]*\n(.*?)(?=^\[|\Z)", text,
                        re.MULTILINE | re.DOTALL | re.IGNORECASE)
    if not section:
        return "absent", None
    default = re.search(r'^@="((?:[^"\\]|\\.)*)"', section.group(1), re.MULTILINE)
    if not default:
        return "other", None
    value = re.sub(r"\\(.)", r"\1", default.group(1))
    return ("ours" if value == HANDLER_VALUE else "other"), value


def outcome(stdout):
    """(outcome word, the line it came from) from questlog_ctl.exe folder-handler's output; (None, text) if absent."""
    for line in stdout.splitlines():
        word = line.split(":", 1)[0].strip()
        if word in OUTCOMES:
            return word, line.strip()
    return None, stdout.strip()


def run_ctl(action):
    """Run questlog_ctl.exe folder-handler <action> in the game's prefix; (outcome, line).

    Raises RuntimeError when it cannot be run or gives no answer.
    """
    from .launcher import CTL
    protontricks = shutil.which("protontricks-launch")
    if not protontricks:
        raise RuntimeError("protontricks-launch is not installed (see 'missing' above)")
    if not CTL.is_file():
        raise RuntimeError(f"{CTL} is missing")
    try:
        done = subprocess.run([protontricks, "--appid", str(APPID), str(CTL), "folder-handler", action],
                              stdin=subprocess.DEVNULL, capture_output=True, text=True, errors="replace",
                              timeout=CTL_WAIT, start_new_session=True)
    except subprocess.TimeoutExpired:
        raise RuntimeError(f"questlog_ctl.exe did not answer within {CTL_WAIT} s") from None
    word, line = outcome(done.stdout)
    if word is None or word == "error":
        tail = [text.strip() for text in done.stderr.splitlines() if text.strip()][-2:]
        raise RuntimeError(f"questlog_ctl.exe folder-handler {action} failed (exit code {done.returncode}): "
                           + " / ".join(([line] if line else []) + tail or ["no output"]))
    return word, line


def setup_step(want, ask, interactive, log=print, ctl=run_ctl):
    """a2qlinux-setup's step. want: True (--open-folders), False (--no-open-folders) or None.

    Returns a problem to note, or None.
    """
    try:
        if want is False:
            word, line = ctl("remove")
            log(f"Open Folder: {line}")
            return None
        word, line = ctl("status")
        if word == "ours":
            log("Open Folder: Questlog's folders open in the file manager.")
            return None
        if word == "other":
            log(f"Open Folder: the prefix already has a command for opening folders; A2Qlinux leaves it ({line}).")
            return None
        if not want:
            if not interactive:
                log("Open Folder is not set up; to let Questlog's Open Folder buttons work, run "
                    "a2qlinux-setup --open-folders")
                return None
            log("\n" + EXPLANATION)
            answer = ask("Set this up now? [Y/n] ").strip().lower()
            if answer not in ("", "y", "yes", "t", "tak"):
                log("Not set up; run a2qlinux-setup --open-folders to do it later.")
                return None
        word, line = ctl("set")
        log(f"Open Folder: {line}")
        return None
    except (OSError, RuntimeError) as error:
        return f"Open Folder: {error}; Questlog's Open Folder buttons keep showing Wine's error"
