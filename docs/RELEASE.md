# Releasing A2Qlinux

Step by step from a clean `develop` to a GitHub Release with the packages
attached. How packaging and CI are built, and why, is in
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

Add a section above the previous one in `CHANGELOG.md`:

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

Publishing creates the tag and starts the `Release` workflow, which builds
the Windows parts, runs the tests, builds the sdist and the wheel, checks the
wheel (both Windows parts inside, version equal to the tag) and attaches both
files to the release.

## 7. Check the result

```bash
gh run watch                                          # Release workflow passes
gh release view vX.Y.Z --json assets --jq '.assets[].name'
#   a2qlinux-X.Y.Z-py3-none-any.whl  and  a2qlinux-X.Y.Z.tar.gz
```

Install the released wheel once in a throwaway pipx location, so the real
installation is not touched:

```bash
mkdir -p /tmp/a2q-check && cd /tmp/a2q-check
gh release download vX.Y.Z --repo raman78/A2Qlinux --pattern '*.whl'
PIPX_HOME=/tmp/a2q-check/home PIPX_BIN_DIR=/tmp/a2q-check/bin pipx install ./a2qlinux-X.Y.Z-py3-none-any.whl
/tmp/a2q-check/home/venvs/a2qlinux/bin/python -c "import a2qlinux; print(a2qlinux.__version__)"
rm -rf /tmp/a2q-check
```

## 8. Back to develop

```bash
git checkout develop
```

## PyPI (once the repository is public)

The `pypi` job in `.github/workflows/release.yml` is off (`if: false`), since a
package on PyPI is public. To turn it on: make the repository public, add a
Trusted Publisher on pypi.org for project `a2qlinux`, repository
`raman78/A2Qlinux`, workflow `release.yml`, then remove the `if: false`. From
the next release on, users install with `pipx install a2qlinux` and update
with `pipx upgrade a2qlinux`; `docs/INSTALL.md` and `docs/UPDATING.md` then
need that change.
