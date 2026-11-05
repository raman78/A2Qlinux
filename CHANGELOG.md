# Changelog

What changed for players, release by release. Technical details are in
`docs/ARCHITECTURE.md`.

## [Unreleased]

### Changed
- The status window no longer prints a line every time Questlog reconnects
  to the game traffic, which it does on every zone change. It says once that
  Questlog is connected; problems are still reported as before.

## [0.2.1] — 2026-11-05

### Fixed
- `a2qlinux-setup --questlog-dir <folder>` now always takes effect: the
  folder is written into the settings file even when that file already
  exists, and the other settings in it stay as they were.

### Changed
- Installing from the source code is one command, `install-from-source.sh`,
  which builds, installs and sets up. The build looks for Wine's files where
  the distributions in the install guide keep them, and names missing build
  tools with the command that installs them.

## [0.2.0] — 2026-11-05

### Changed
- A2Qlinux is now installed and updated from PyPI: `pipx install a2qlinux`,
  then `pipx upgrade a2qlinux` for new versions. After updating from 0.1.0,
  which was installed from a downloaded file, switch over once: quit
  Questlog, then run `pipx uninstall a2qlinux && pipx install a2qlinux`. The
  menu entry, the Steam launch option and the settings stay as they are.
- Play in Steam (with the launch option) starts Questlog first and the game
  a few seconds later, once Questlog runs, instead of the other way round.
  That is what lets the game end without disturbing Questlog.
- Quit Questlog ends it at once when no game data is waiting to be saved
  (without the game, or a while after closing it); while playing, it still
  waits until the last data is saved, at most about 10 seconds.
- The status window opens in the terminal the desktop has (GNOME Terminal,
  Ptyxis, the Xfce or MATE terminal, Debian's default terminal or xterm),
  not only in Konsole. Without any, a notification says which to install.

### Added
- `a2qlinux-setup` installs Questlog when it is not there yet: it downloads
  the newest version from Questlog's authors, checks it and puts it in
  place. Installing Questlog by hand is no longer needed.
- `a2qlinux-setup` checks everything A2Qlinux needs, including that
  capturing the game's traffic is allowed and that the tray icon can run on
  the desktop, and for anything missing prints the exact command for the
  distribution in use.
- A settings file, `~/.config/a2qlinux/config.toml`, created by
  `a2qlinux-setup`: Questlog's folder, what happens after the game (Questlog
  stays or closes, and after how long it closes), and automatic updates.
  Mistakes in it are reported with their line, and the default is used
  meanwhile.
- The install guide covers Debian, Ubuntu, Fedora and openSUSE besides
  Arch, in numbered steps with one package command per distribution, and
  says what A2Qlinux needs from the desktop and from Steam.

### Fixed
- Steam no longer shows AION 2 as running after the game is closed while
  Questlog stays open: a moment after the game ends, Steam shows Play again,
  and Questlog keeps running untouched. Only when the game was started
  before Questlog does Questlog restart, about 10 seconds after the game, as
  it was (window open or only in the tray).
- AION 2's Proton environment is found wherever Steam is installed, not
  only in its default folder. A Steam from Flatpak, which A2Qlinux cannot
  work with, is named as the reason.

## [0.1.0] — 2026-10-18

First release.

### Added
- Questlog Desktop runs next to AION 2 on Linux, inside the game's Proton
  environment, with live game traffic: the damage meter, boss HP and alerts
  work as on Windows.
- Questlog can be started before, after or together with the game; with the
  Steam launch option it starts with the game, and pressing Play while
  Questlog is open lets the game join it.
- Clicks in the game stay in the game while Questlog's window is open behind
  it.
- A tray icon with Open and Quit that works every time, in place of
  Questlog's own, whose menu opens only once under Proton.
- Quitting Questlog waits until it has saved its data, without touching the
  game; opening it again within those seconds keeps it running.
- Questlog is kept up to date: new versions are downloaded in the background
  (never while the game runs), checked, installed at the next start, and
  rolled back if they do not start.
- Installation with pipx; `a2qlinux-setup` creates the "Questlog (AION 2)"
  menu entry, which keeps itself pointing at the installed program.
