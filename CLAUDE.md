# A2Qlinux — context for Claude

A2Qlinux runs Questlog Desktop (closed-source, Windows-only Electron damage
meter for AION 2) inside the game's Proton prefix on Linux, fed with live game
traffic through our own `wpcap.dll`. Developed on CachyOS, KDE Plasma (Wayland),
Steam with `proton-cachyos-slr`.

**Before answering**, open the doc index and read the matching document whole:

| Question | Document |
|---|---|
| how it works, why, failure modes, tests, what a Questlog update can break | `docs/ARCHITECTURE.md` |
| installing, daily use, tray icon, updating Questlog, troubleshooting (user guides) | `docs/INSTALL.md`, `docs/USING.md`, `docs/UPDATING.md`, `docs/TROUBLESHOOTING.md` |
| other meters, NotMeter, game rules, network diagnostics, own-program idea (private, Polish, not in git) | `notes/README.md` |

Code: the package `a2qlinux/` (commands `a2qlinux`, `a2qlinux-run`,
`a2qlinux-setup`, `a2qlinux-steam`), C sources in `bridge/`. Tests:
`python3 -m unittest` in the repository root, after `bash bridge/build.sh`
(also after a Wine update). Installed here with `pipx install --editable .`.
Work on `develop`; releases per `docs/RELEASE.md` (`main` = last release).

A change to the code is not finished until `docs/ARCHITECTURE.md` and, where
users see it, the user guide concerned match it — in the same commit. When something
about the machine's setup changes (Questlog version, paths, launch method),
update the "Stan" section of `notes/README.md`.

Rules learned in this project:
- Never run meters or scripts with `sudo`; capture works through the
  `wireshark` group.
- Never `wineserver -k` in the game prefix — it ends the game too. Questlog's
  processes carry Chromium names (`CrBrowserMain`, …); find them by command
  line.
- The game prefix (`steamapps/compatdata/3393110/pfx`) is game data. Test
  third-party programs in a separate throwaway prefix and delete it after the
  test; run window tests under `xvfb-run` so they take no focus.
- Act on Questlog only: no prefix- or session-wide switches that would reach
  the game or other programs there (NotMeter).
- `notes/` is private and stays out of git; never quote it into committed files
  (it holds personal network details).
