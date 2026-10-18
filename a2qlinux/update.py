"""Keep Questlog up to date under Proton, where its own installer cannot run.

Questlog updates itself with electron-updater: it downloads the new installer
in the background and runs it on quit. Under Wine that installer stops with
code 2 (docs/ARCHITECTURE.md §7.5), so the launcher does the update instead,
the way docs/UPDATING.md describes doing it by hand:

  while Questlog runs   stage(): read the feed, download the installer, check
                        size and SHA-512, unpack it, check that the new
                        version still fits A2Qlinux (compatibility_problems),
                        and leave it in <state>/update/<version>/app
  before the next start install_staged(): swap the Questlog folder for the
                        staged one, keeping the old one as a backup
  if it then fails      rollback(): put the old folder back

Questlog's own updater is switched off (disable_builtin_updater), so it no
longer downloads 115 MB that it cannot install, nor offers an install button
that does nothing. Without resources/app-update.yml it only logs
"[updater] … ENOENT" every five minutes; nothing else changes (tested).

Nothing here is silent: each step reports through the `log` callback, and
what the user should know (an update ready, an update that does not fit) goes
to `notify` as well.
"""

import base64
import hashlib
import json
from pathlib import Path
import re
import shutil
import struct
import subprocess
import threading
import urllib.request

FEED = "https://cdn.questlog.gg/desktop/latest.yml"
DOWNLOADS = "https://cdn.questlog.gg/desktop/"
# The libpcap calls bridge/wpcap_bridge.c implements.
PCAP_CALLS = {"pcap_close", "pcap_compile", "pcap_datalink", "pcap_findalldevs", "pcap_freealldevs",
              "pcap_freecode", "pcap_geterr", "pcap_next_ex", "pcap_open_live", "pcap_setfilter",
              "pcap_setnonblock"}
# Electron versions whose tray icon id and WM_ENDSESSION handling were read in
# their source (questlog_ctl.exe depends on both; docs/ARCHITECTURE.md §10).
KNOWN_ELECTRON = {"44.5.1"}
STATE_FILE = "staged.json"
# The CDN refuses Python's default User-Agent (403); it accepts one that names us.
USER_AGENT = "A2Qlinux (Questlog updater for Linux)"
# Held while staging or installing, so an install never meets a half-written stage.
BUSY = threading.Lock()


# ------------------------------------------------------------------ archive

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


def version_key(version):
    return tuple(int(part) for part in re.findall(r"\d+", version))


def installed_version(questlog_dir):
    """Questlog's version from its app.asar; None if it cannot be read."""
    try:
        package = read_asar_file(Path(questlog_dir) / "resources" / "app.asar", "package.json")
        return json.loads(package)["version"]
    except (OSError, KeyError, ValueError, struct.error):
        return None


def parse_feed(text):
    """version, installer file name, SHA-512 (base64) and size from latest.yml.

    The file is electron-builder's fixed format; only its top-level scalars
    and the first entry of `files` are needed, so no YAML library is used.
    """
    found = {}
    for line in text.splitlines():
        match = re.match(r"^(version|path|sha512):\s*'?([^']+?)'?\s*$", line)
        if match:
            found[match.group(1)] = match.group(2)
        match = re.match(r"^\s+size:\s*(\d+)\s*$", line)
        if match and "size" not in found:
            found["size"] = int(match.group(1))
    missing = {"version", "path", "sha512", "size"} - found.keys()
    if missing:
        raise ValueError(f"latest.yml lacks {', '.join(sorted(missing))}")
    if "/" in found["path"] or not found["path"].endswith(".exe"):
        raise ValueError(f"latest.yml names an unexpected installer: {found['path']!r}")
    return found


# ------------------------------------------------------------ compatibility

def compatibility_problems(app_dir):
    """What in an unpacked Questlog would break A2Qlinux; an empty list means it fits.

    The checks listed in docs/ARCHITECTURE.md §10.
    """
    app_dir = Path(app_dir)
    asar = app_dir / "resources" / "app.asar"
    problems = []
    try:
        main = read_asar_file(asar, ".output/electron/main.cjs").decode("utf-8", "replace")
        worker = read_asar_file(asar, ".output/electron/workers/aion-2/combat.cjs").decode("utf-8", "replace")
    except (OSError, KeyError, ValueError, struct.error) as error:
        return [f"its app.asar could not be read ({error!r})"]
    calls = set(re.findall(r"(pcap_[a-z_]+)\(", worker))
    if calls - PCAP_CALLS:
        problems.append(f"it calls libpcap functions the bridge DLL lacks: {', '.join(sorted(calls - PCAP_CALLS))}")
    if not calls:
        problems.append("its capture worker calls no libpcap functions any more")
    electron = re.search(rb"Electron/(\d+\.\d+\.\d+)", (app_dir / "Questlog.exe").read_bytes()) \
        if (app_dir / "Questlog.exe").is_file() else None
    if not electron:
        problems.append("its Electron version could not be read")
    elif electron.group(1).decode() not in KNOWN_ELECTRON:
        problems.append(f"it uses Electron {electron.group(1).decode()}, not yet checked "
                        f"(known: {', '.join(sorted(KNOWN_ELECTRON))}); its tray icon id and session end "
                        "need reading in that version's source")
    if not re.search(r'on\("second-instance",[A-Za-z0-9_$]+\.show\)', main):
        problems.append("a second start no longer simply shows its window (Open Questlog relies on it)")
    if "focusable:!1" not in main:
        problems.append("its overlay windows are no longer non-activatable (the window-order guard relies on it)")
    try:
        read_asar_file(asar, "resources/icon.png")
    except (KeyError, OSError):
        problems.append("its icon resources/icon.png is gone (a2qlinux-setup takes it from there)")
    return problems


# --------------------------------------------------------------- built-in updater

def disable_builtin_updater(questlog_dir, log):
    """Remove resources/app-update.yml, which is all Questlog's own updater runs on."""
    config = Path(questlog_dir) / "resources" / "app-update.yml"
    if config.exists():
        config.unlink()
        log("Switched off Questlog's own updater (its installer cannot run under Wine); "
            "A2Qlinux updates Questlog instead.")


# ------------------------------------------------------------------ staging

def _open(url, timeout):
    return urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": USER_AGENT}), timeout=timeout)


def _download(url, target, size, sha512_b64, timeout=60):
    digest = hashlib.sha512()
    got = 0
    with _open(url, timeout) as response, open(target, "wb") as out:
        while chunk := response.read(1 << 20):
            out.write(chunk)
            digest.update(chunk)
            got += len(chunk)
    if got != size:
        raise ValueError(f"downloaded {got} bytes, latest.yml says {size}")
    if base64.b64encode(digest.digest()).decode() != sha512_b64:
        raise ValueError("the download's SHA-512 does not match latest.yml")


def _unpack(installer, work):
    """installer.exe (NSIS) -> work/app, Questlog's files; needs 7z."""
    seven = shutil.which("7z")
    if not seven:
        raise RuntimeError("7z is missing (package p7zip)")
    nsis, app = work / "nsis", work / "app"
    for folder in (nsis, app):
        shutil.rmtree(folder, ignore_errors=True)
        folder.mkdir(parents=True)
    for archive, into in ((installer, nsis), (nsis / "$PLUGINSDIR" / "app-64.7z", app)):
        done = subprocess.run([seven, "x", "-y", f"-o{into}", str(archive)], capture_output=True, text=True)
        if done.returncode:
            raise RuntimeError(f"7z could not unpack {archive.name}: {done.stderr.strip() or done.stdout[-300:]}")
    shutil.rmtree(nsis)
    if not (app / "Questlog.exe").is_file():
        raise RuntimeError("the installer did not contain Questlog.exe where expected")
    return app


def read_state(state_dir):
    try:
        return json.loads((Path(state_dir) / "update" / STATE_FILE).read_text())
    except (OSError, ValueError):
        return {}


def write_state(state_dir, state):
    path = Path(state_dir) / "update" / STATE_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, indent=1))


def stage(questlog_dir, state_dir, log, notify, feed_url=FEED, downloads=DOWNLOADS):
    """Check for a newer Questlog and stage it for the next start. Returns the staged state.

    Network or format errors are logged and end this attempt; the next check
    tries again. A version already staged or already judged is not fetched again.
    """
    with BUSY:
        return _stage(questlog_dir, state_dir, log, notify, feed_url, downloads)


def _stage(questlog_dir, state_dir, log, notify, feed_url, downloads):
    current = installed_version(questlog_dir)
    try:
        with _open(feed_url, 20) as response:
            feed = parse_feed(response.read().decode("utf-8", "replace"))
    except (OSError, ValueError) as error:
        log(f"Questlog update check failed ({error}); trying again later.")
        return None
    if current and version_key(feed["version"]) <= version_key(current):
        return None
    state = read_state(state_dir)
    if state.get("version") == feed["version"]:
        return state                                   # already staged or already refused
    work = Path(state_dir) / "update" / feed["version"]
    log(f"Questlog {feed['version']} is out (installed: {current or 'unknown'}); downloading it.")
    try:
        work.mkdir(parents=True, exist_ok=True)
        installer = work / feed["path"]
        _download(downloads + feed["path"], installer, feed["size"], feed["sha512"])
        app = _unpack(installer, work)
        installer.unlink()
    except (OSError, ValueError, RuntimeError) as error:
        shutil.rmtree(work, ignore_errors=True)
        log(f"Questlog {feed['version']} could not be staged: {error}. Trying again later.")
        return None
    problems = compatibility_problems(app)
    (app / "resources" / "app-update.yml").unlink(missing_ok=True)
    state = {"version": feed["version"], "app": str(app), "fits": not problems, "problems": problems}
    # Older staged versions are superseded by this one.
    for other in (Path(state_dir) / "update").iterdir():
        if other.is_dir() and other != work:
            shutil.rmtree(other, ignore_errors=True)
    write_state(state_dir, state)
    if problems:
        shutil.rmtree(app, ignore_errors=True)
        text = (f"Questlog {feed['version']} does not fit this A2Qlinux yet, so it was not installed; "
                f"Questlog {current} stays. Why: " + "; ".join(problems) + ".")
        log(text)
        notify(text)
    else:
        log(f"Questlog {feed['version']} is downloaded and checked; it is installed the next time "
            "Questlog starts.")
        notify(f"Questlog {feed['version']} is ready. It is installed the next time Questlog starts.")
    return state


# ------------------------------------------------------------- installation

def install_staged(questlog_dir, state_dir, log):
    """Swap in a staged version that fits. Returns (old version, backup folder) or None.

    Must run while Questlog does not. The state folder (proton-stream) lives in
    the Questlog folder, so it moves across with the swap; the launcher's lock
    stays held, since it is an open file that moves with its folder. Skipped
    (None) while a download is being staged; the next start installs it.
    """
    if not BUSY.acquire(blocking=False):
        log("A Questlog update is still being downloaded; it is installed at a later start.")
        return None
    try:
        return _install_staged(Path(questlog_dir).resolve(), Path(state_dir).resolve(), log)
    finally:
        BUSY.release()


def _install_staged(questlog_dir, state_dir, log):
    state = read_state(state_dir)
    app = Path(state.get("app", "")).resolve()
    if not state.get("fits") or not (app / "Questlog.exe").is_file():
        return None
    old = installed_version(questlog_dir) or "previous"
    backup = questlog_dir.with_name(f"{questlog_dir.name}-{old}")
    if backup.exists():
        backup = questlog_dir.with_name(f"{questlog_dir.name}-{old}-a2q")
    if backup.exists():
        log(f"Questlog {state['version']} is staged, but {backup} is in the way; not installed.")
        return None
    staged_rel = app.relative_to(questlog_dir)          # app sits inside the folder being moved
    questlog_dir.rename(backup)
    (backup / staged_rel).rename(questlog_dir)
    (backup / state_dir.name).rename(questlog_dir / state_dir.name)
    shutil.rmtree(state_dir / "update", ignore_errors=True)
    previous = read_backup_record(state_dir)
    write_backup_record(state_dir, {"version": old, "path": str(backup), "installed": state["version"]})
    # Keep one backup: the one this update made. Older backups made by A2Qlinux go.
    if previous and Path(previous.get("path", "")).is_dir() and Path(previous["path"]) != backup:
        shutil.rmtree(previous["path"], ignore_errors=True)
        log(f"Removed the older backup {previous['path']}.")
    log(f"Installed Questlog {state['version']}; Questlog {old} is kept in {backup}.")
    return old, backup


def read_backup_record(state_dir):
    try:
        return json.loads((Path(state_dir) / "questlog-backup.json").read_text())
    except (OSError, ValueError):
        return {}


def write_backup_record(state_dir, record):
    (Path(state_dir) / "questlog-backup.json").write_text(json.dumps(record, indent=1))


def rollback(questlog_dir, state_dir, log):
    """Put the backup made by the last install_staged back. Returns True if done."""
    questlog_dir, state_dir = Path(questlog_dir), Path(state_dir)
    record = read_backup_record(state_dir)
    backup = Path(record.get("path", ""))
    if not (backup / "Questlog.exe").is_file():
        log("No Questlog backup to go back to.")
        return False
    failed = questlog_dir.with_name(f"{questlog_dir.name}-{record.get('installed', 'failed')}-failed")
    shutil.rmtree(failed, ignore_errors=True)
    questlog_dir.rename(failed)
    backup.rename(questlog_dir)
    (failed / state_dir.name).rename(questlog_dir / state_dir.name)
    (state_dir / "questlog-backup.json").unlink(missing_ok=True)
    write_state(state_dir, {"version": record.get("installed"), "fits": False,
                            "problems": ["it did not start under Proton after installing"]})
    log(f"Went back to Questlog {record.get('version')}; the version that failed is in {failed}.")
    return True
