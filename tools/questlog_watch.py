"""Judge each new Questlog version as it appears, record it, and open an issue when it does not fit.

Run by .github/workflows/questlog-watch.yml on a checkout of `main` (the last
release, which is what a player installs), with the register's branch
checked out beside it; docs/ARCHITECTURE.md §12 "Watching Questlog's
releases". The judging is A2Qlinux's own: update.read_feed and update._fetch,
the download, size and SHA-512 check, unpacking and compatibility_problems
that a player's update runs.

  python -m tools.questlog_watch --register REGISTER.json
      the feed's newest version, if the register has no verdict on it yet, or
      only a refusal by other checks than these
  python -m tools.questlog_watch --register REGISTER.json --version 0.1.54
      an older version the feed no longer describes: its size and SHA-512 are
      worked out from the CDN's file (recorded as "computed")

Issues: a refusal opens one (label questlog-compat), unless the register or
GitHub already has one for that version; a later refusal by newer checks
comments on it; a later fit closes it with a comment. `gh` does the talking
to GitHub. Prints what it did; exits non-zero when a step fails, so the
workflow run fails visibly.
"""

import argparse
import base64
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile

from a2qlinux import questlog_versions, shown_version, update

LABEL = "questlog-compat"


def issue_title(version):
    return f"Questlog {version} does not fit A2Qlinux"


def issue_body(version, entry):
    reasons = "\n".join(f"- {problem}" for problem in entry["problems"])
    return (f"The Questlog watch judged Questlog {version} with A2Qlinux {entry['checked_by']}'s "
            f"compatibility checks on {entry['checked_at']}. It does not fit:\n\n{reasons}\n\n"
            "Players who have Questlog keep their installed version; their A2Qlinux tells them it refused "
            "this one. `a2qlinux-setup` on a machine without Questlog cannot install it.\n\n"
            "What each check relies on, and how to check it by hand: docs/ARCHITECTURE.md §10. "
            "If the check is a false alarm, fix it and release; the watch then judges the version "
            "again and closes this issue.")


def gh(*args):
    done = subprocess.run(["gh", *args], capture_output=True, text=True)
    if done.returncode:
        raise RuntimeError(f"gh {' '.join(args[:2])} failed: {done.stderr.strip()}")
    return done.stdout


def find_issue(version, run=gh):
    """The number of an issue (open or closed) already titled for this version, else None."""
    issues = json.loads(run("issue", "list", "--state", "all", "--label", LABEL, "--limit", "200",
                            "--json", "number,title"))
    return next((issue["number"] for issue in issues if issue["title"] == issue_title(version)), None)


def report(version, entry, run=gh, say=print):
    """Open, comment on or close the version's issue to match the entry's verdict."""
    if not entry["fits"]:
        number = entry["issue"] or find_issue(version, run)
        if number is None:
            url = run("issue", "create", "--title", issue_title(version), "--label", LABEL,
                      "--body", issue_body(version, entry)).strip()
            entry["issue"] = int(url.rstrip("/").rsplit("/", 1)[-1])
            say(f"Opened issue #{entry['issue']}: {url}")
        else:
            entry["issue"] = number
            run("issue", "comment", str(number), "--body", issue_body(version, entry))
            say(f"Commented on issue #{number}: still refused, by A2Qlinux {entry['checked_by']}.")
    elif entry["issue"]:
        run("issue", "close", str(entry["issue"]), "--comment",
            f"Questlog {version} fits A2Qlinux {entry['checked_by']} (checked {entry['checked_at']}).")
        say(f"Closed issue #{entry['issue']}: Questlog {version} fits A2Qlinux {entry['checked_by']}.")


def needs_judging(register, version, checks):
    """No verdict yet, or a refusal by other checks than these (they may have been fixed)."""
    entry = register["versions"].get(version)
    return entry is None or (not entry["fits"] and entry["checked_by"] != checks)


def describe_older(version, into, downloads=update.DOWNLOADS):
    """A feed-like description of an older version, its file downloaded into `into` to work out size and SHA-512.

    Returns (feed, downloads URL that serves the downloaded file).
    """
    path = f"questlog-setup-{version}.exe"
    digest, size = hashlib.sha512(), 0
    with update._open(downloads + path, 60) as response, open(into / path, "wb") as out:
        while chunk := response.read(1 << 20):
            out.write(chunk)
            digest.update(chunk)
            size += len(chunk)
    feed = {"version": version, "path": path, "size": size, "sha512": base64.b64encode(digest.digest()).decode()}
    return feed, into.resolve().as_uri() + "/"


def watch(register_path, version=None, run=gh, say=print, feed_url=update.FEED, downloads=update.DOWNLOADS,
          now=None):
    """One pass; returns True when the register changed."""
    register = questlog_versions.load(register_path)
    checks = shown_version()
    with tempfile.TemporaryDirectory(prefix="questlog-watch-") as work:
        work = Path(work)
        if version is None:
            feed, sha512_from = update.read_feed(feed_url), "latest.yml"
            if not needs_judging(register, feed["version"], checks):
                say(f"Questlog {feed['version']} is the newest; already judged "
                    f"({'fits' if register['versions'][feed['version']]['fits'] else 'refused'}, "
                    f"by A2Qlinux {register['versions'][feed['version']]['checked_by']}).")
                return False
        else:
            (work / "cdn").mkdir()
            feed, downloads = describe_older(version, work / "cdn", downloads)
            sha512_from = "computed"
        say(f"Judging Questlog {feed['version']} with A2Qlinux {checks}'s checks.")
        (work / "unpack").mkdir()
        _app, problems = update._fetch(feed, work / "unpack", downloads)
    checked_at = (now or datetime.now(timezone.utc)).strftime("%Y-%m-%dT%H:%M:%SZ")
    entry = questlog_versions.record(register, feed, problems, checks, checked_at, sha512_from)
    say(f"Questlog {feed['version']}: " + ("fits." if entry["fits"] else "refused: " + "; ".join(problems)))
    try:
        report(feed["version"], entry, run, say)
    finally:
        questlog_versions.save(register_path, register)   # an opened issue is recorded even if a later step fails
    return True


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--register", type=Path, required=True)
    parser.add_argument("--version", help="judge this older version instead of the feed's newest")
    args = parser.parse_args(argv)
    changed = watch(args.register, args.version)
    print(f"changed={'true' if changed else 'false'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
