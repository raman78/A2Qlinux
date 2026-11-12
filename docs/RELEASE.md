# Releasing A2Qlinux

Step by step from a clean `develop` to a GitHub Release with the packages
attached and the same packages on PyPI. How packaging and CI are built, and why, is in
`docs/ARCHITECTURE.md` §12.

## Requirements

- `gh` logged in (`gh auth status`), with push access to `origin`.
- A clean working tree on `develop`.

## 1. Check the state

```bash
git status                                  # clean
git rev-parse --abbrev-ref HEAD             # develop
git fetch origin && git log origin/develop..develop   # empty: pushed
gh run list --branch develop --limit 3      # Tests green for the last commit
git tag --sort=-v:refname | head -3         # last version
git log <last tag>..develop --oneline       # what goes into this release
```

Then check that the newest Questlog fits this A2Qlinux. Players run the
newest Questlog, because A2Qlinux updates it by itself, so a release that
does not fit it ships a refused update. The check runs the shipped updater
(`stage()` in `a2qlinux/update.py`: download, checksum, unpack,
`compatibility_problems`) against a throwaway folder; the real Questlog is
not touched. Run it from the repository root (about 125 MB download):

```bash
rm -rf /tmp/a2q-qlcheck && mkdir -p /tmp/a2q-qlcheck/questlog /tmp/a2q-qlcheck/state
python3 -c "
import sys, json
from a2qlinux import update
state = update.stage('/tmp/a2q-qlcheck/questlog', '/tmp/a2q-qlcheck/state', print, lambda t: None)
print(json.dumps(state, indent=1))
sys.exit(0 if state and state['fits'] else 1)
"; rm -rf /tmp/a2q-qlcheck
```

`"fits": true` means release. `"fits": false` lists in `problems` what
changed in Questlog; that needs a code change first
(`docs/ARCHITECTURE.md` §10). No output state (`None`) means the feed or
the download failed; the line above it says why.

## 2. Choose the version

Tags are `vMAJOR.MINOR.PATCH`; the package version is the tag without `v`
(hatch-vcs reads it at build time, nothing to edit in the code).

| Change | Bump |
|---|---|
| fixes only | patch |
| new behaviour players notice | minor |
| something players must redo (launch option, menu entry, reinstall) | minor, and say so in the changelog |

## 3. Write the changelog

Changes are collected under `## [Unreleased]` while they are made; rename
that heading to the version and date. Without such a section, add one above the
previous release in `CHANGELOG.md`:

```markdown
## [X.Y.Z] — YYYY-MM-DD

### Added
- ...

### Fixed
- ...
```

Rules, as in sto-warp: written for a player, not a programmer; no file,
module, function or variable names; no commit or issue links; neutral tone
("Questlog does X"); related fixes merged into one bullet. If players have to
do something after updating, it is the first bullet. The release title, also
the release commit's one-liner, follows the same rules:
`vX.Y.Z — short player-facing summary`. Everything published is in
English.

## 4. Release commit on develop

```bash
git add CHANGELOG.md
git commit -m "release: vX.Y.Z — short player-facing summary"
git push origin develop
gh run watch                                # wait for Tests to pass
```

## 5. Fast-forward main

```bash
git checkout main
git pull --ff-only origin main
git merge --ff-only develop
git push origin main
```

If `--ff-only` refuses, stop: `main` has commits `develop` lacks. Find out
why and resolve it by hand; never force.

## 6. Publish the release

```bash
awk '/^## \[/{keep = index($0, "[X.Y.Z]") > 0} keep' CHANGELOG.md | tail -n +2 > /tmp/a2q-vX.Y.Z-notes.md
gh release create vX.Y.Z --target main --title "vX.Y.Z — short player-facing summary" --notes-file /tmp/a2q-vX.Y.Z-notes.md
```

Publishing creates the tag and starts the `Release` workflow. Its `build`
job builds the Windows parts, runs the tests, builds the sdist and the wheel,
checks the wheel (both Windows parts inside, version equal to the tag) and
attaches both files to the release. Its `pypi` job then uploads those two
files to PyPI.

## 7. Check the result

```bash
gh run watch                                          # Release workflow passes, both jobs
gh release view vX.Y.Z --json assets --jq '.assets[].name'
#   a2qlinux-X.Y.Z-py3-none-any.whl  and  a2qlinux-X.Y.Z.tar.gz
curl -fsSL https://pypi.org/pypi/a2qlinux/json | python3 -c "import json,sys; print(json.load(sys.stdin)['info']['version'])"
#   X.Y.Z  (PyPI's JSON can lag a minute behind the upload)
```

Install from PyPI once in a throwaway pipx location, so the real installation
is not touched, and check that the Windows parts came with it:

```bash
mkdir -p /tmp/a2q-check
PIPX_HOME=/tmp/a2q-check/home PIPX_BIN_DIR=/tmp/a2q-check/bin pipx install a2qlinux==X.Y.Z
/tmp/a2q-check/home/venvs/a2qlinux/bin/python -I -c "import a2qlinux, pathlib; print(a2qlinux.__file__, a2qlinux.__version__, sorted(p.name for p in (pathlib.Path(a2qlinux.__path__[0]) / 'bin').iterdir()))"
#   /tmp/a2q-check/home/venvs/…/site-packages/a2qlinux/__init__.py X.Y.Z ['questlog_ctl.exe', 'wpcap.dll']
rm -rf /tmp/a2q-check
```

`-I` keeps Python from importing the `a2qlinux` folder of the current
directory: run from the repository root without it, the check reads the
checkout's stale `_version.py` instead of the installed package (seen at
the 0.6.0 release, which showed `0.4.1.dev2`). The path printed first
must lie under `/tmp/a2q-check`.

If the `pypi` job failed while `build` passed, the release and its files
are fine; fix the cause (usually the Trusted Publisher settings on pypi.org)
and re-run only that job: `gh run rerun <run id> --failed`.

## 8. Back to develop

```bash
git checkout develop
git fetch origin            # brings the new tag: gh release create made it on GitHub only
git describe --tags         # vX.Y.Z or vX.Y.Z-<n>-g<commit>
```

Without the fetch an editable installation on this machine goes on
showing the previous version plus a commit count (`docs/ARCHITECTURE.md`
§12, "Shown version").

## PyPI

Publishing needs a Trusted Publisher on pypi.org: project `a2qlinux`, owner
`raman78`, repository `A2Qlinux`, workflow `release.yml`, no environment.
Without it the `pypi` job fails with an OIDC "invalid-publisher" error. How
the job is built, and why it uploads the release's files instead of building
again: `docs/ARCHITECTURE.md` §12.

A version on PyPI cannot be replaced, only yanked. A broken release is
followed by a new patch release, never by re-tagging the same version.
