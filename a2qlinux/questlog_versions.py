"""The register of Questlog versions and how A2Qlinux judged them (docs/ARCHITECTURE.md §12).

Questlog's feed (latest.yml) describes only its newest version. Older
installers stay on the CDN, but nothing there says how large they are, what
their SHA-512 is, or whether they fit A2Qlinux. The watch workflow
(.github/workflows/questlog-watch.yml, tools/questlog_watch.py) therefore
records every new version while it is the feed's newest: its size and
SHA-512 as the feed gives them, and the verdict of compatibility_problems.
a2qlinux-setup reads it (read, older_fitting) when the newest version does
not fit, to install the newest earlier one that does (update.install_fresh).
The register lives on the branch `questlog-versions` as one JSON file:

  {"format": 1,
   "versions": {"0.1.56": {"path": "questlog-setup-0.1.56.exe",
                           "size": 129748160, "sha512": "<base64>",
                           "sha512_from": "latest.yml",
                           "fits": true, "problems": [],
                           "checked_by": "0.7.4 (source checkout)",
                           "checked_at": "2026-11-18T12:00:00Z",
                           "issue": null}}}

sha512_from is "latest.yml" when the feed named the checksum, or
"computed" when it was worked out from the CDN's file after the feed had
moved on (the first entries only). issue is the GitHub issue opened for a
refusal, if any.
"""

import json
from pathlib import Path
import re
import urllib.request

FORMAT = 1
FILE = "questlog-versions.json"
BRANCH = "questlog-versions"
# Where a2qlinux-setup reads the register (update.install_fresh).
URL = f"https://raw.githubusercontent.com/raman78/A2Qlinux/{BRANCH}/{FILE}"


def empty():
    return {"format": FORMAT, "versions": {}}


def load(path):
    """The register in `path`; an empty one if the file does not exist yet."""
    path = Path(path)
    if not path.exists():
        return empty()
    return _checked(json.loads(path.read_text()), path)


def _checked(register, where):
    if register.get("format") != FORMAT or not isinstance(register.get("versions"), dict):
        raise ValueError(f"{where} is not a register of format {FORMAT}")
    return register


def read(url=URL, timeout=20):
    """The register as published; raises OSError or ValueError."""
    with urllib.request.urlopen(url, timeout=timeout) as response:
        return _checked(json.loads(response.read().decode("utf-8")), url)


def older_fitting(register, below):
    """Feed-like descriptions of the versions older than `below` the register says fit, newest first."""
    found = []
    for version, entry in register["versions"].items():
        if not re.fullmatch(r"\d+(\.\d+)+", version) or version_key(version) >= version_key(below):
            continue
        if not entry.get("fits") or not re.fullmatch(r"[\w.-]+\.exe", str(entry.get("path", ""))):
            continue
        found.append({"version": version, "path": entry["path"], "size": entry["size"], "sha512": entry["sha512"]})
    return sorted(found, key=lambda feed: version_key(feed["version"]), reverse=True)


def save(path, register):
    Path(path).write_text(json.dumps(register, indent=1, sort_keys=True) + "\n")


def version_key(version):
    """Sort key for Questlog's versions (0.1.9 < 0.1.10)."""
    return tuple(int(part) for part in version.split("."))


def record(register, feed, problems, checked_by, checked_at, sha512_from="latest.yml"):
    """Enter (or replace) the verdict on the feed's version; returns the entry.

    An issue already opened for the version is kept, so a later verdict can
    close it.
    """
    entry = {"path": feed["path"], "size": feed["size"], "sha512": feed["sha512"], "sha512_from": sha512_from,
             "fits": not problems, "problems": list(problems), "checked_by": checked_by,
             "checked_at": checked_at,
             "issue": register["versions"].get(feed["version"], {}).get("issue")}
    register["versions"][feed["version"]] = entry
    return entry
