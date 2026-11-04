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
do something after updating, it is the first bullet.

## 4. Release commit on develop

```bash
git add CHANGELOG.md
git commit -m "release: vX.Y.Z — short description"
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
awk '/^## \[/{keep = index($0, "[X.Y.Z]") > 0} keep' CHANGELOG.md > /tmp/notes.md
gh release create vX.Y.Z --target main --title "A2Qlinux X.Y.Z" --notes-file /tmp/notes.md
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
/tmp/a2q-check/home/venvs/a2qlinux/bin/python -c "import a2qlinux, pathlib; print(a2qlinux.__version__, sorted(p.name for p in (pathlib.Path(a2qlinux.__path__[0]) / 'bin').iterdir()))"
#   X.Y.Z ['questlog_ctl.exe', 'wpcap.dll']
rm -rf /tmp/a2q-check
```

If the `pypi` job failed while `build` passed, the release and its files
are fine; fix the cause (usually the Trusted Publisher settings on pypi.org)
and re-run only that job: `gh run rerun <run id> --failed`.

## 8. Back to develop

```bash
git checkout develop
```

## PyPI

Publishing needs a Trusted Publisher on pypi.org: project `a2qlinux`, owner
`raman78`, repository `A2Qlinux`, workflow `release.yml`, no environment.
Without it the `pypi` job fails with an OIDC "invalid-publisher" error. How
the job is built, and why it uploads the release's files instead of building
again: `docs/ARCHITECTURE.md` §12.

A version on PyPI cannot be replaced, only yanked. A broken release is
followed by a new patch release, never by re-tagging the same version.
