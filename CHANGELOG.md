# Changelog

What changed for players, release by release. Technical details are in
`docs/ARCHITECTURE.md`.

## [Unreleased]

### Fixed
- A Questlog that gets stuck while starting (its window stays empty and it
  counts no fights, because of a rare fault in Wine) is noticed within a
  few seconds, ended and started again, without touching the game. Only if
  the second start gets stuck too does A2Qlinux stop and say so.

### Changed
- The menu entry, the desktop shortcut and the tray icon are called
  **A2Qlinux** instead of "Questlog (AION 2)", and their icon is Questlog's
  Q in red, so they are told apart from Questlog's own icon. Searching the
  menu for "Questlog" still finds the entry. Existing entries are renamed
  on the next start, keeping any options added to them by hand.

## [0.5.0] — 2026-11-10

### Added
- `a2qlinux --diagnose` checks what A2Qlinux needs and how AION 2 is
  started from Steam, without changing anything, and prints one line per
  check: `ok`, `note`, or `PROBLEM` with what to do. It notices, for
  example, a missing Steam launch option, one that keeps the game from
  starting, and a Questlog that was started outside A2Qlinux, which the
  game would wait for.
- `a2qlinux --diagnose --report` also writes a report file with that
  diagnosis and A2Qlinux's recent messages, with the home folder, user
  name, computer name, Steam account number and network addresses
  replaced, shows it, and on request opens a filled-in GitHub issue in
  the browser. Nothing is sent until the issue is submitted.
- Which A2Qlinux runs is shown as the first, greyed-out line of the tray
  icon's menu, when hovering over the icon, as the first line of the
  status window, and by `a2qlinux --version`.
- Everything the status window shows is also kept, with the time, in
  `launcher.log` in the `proton-stream` folder inside Questlog's folder,
  so it is still there after the window has closed. At most 2 MB are
  kept.

### Changed
- At its end, `a2qlinux-setup` says whether AION 2's Steam launch option
  is set, and prints the line to paste only when it is not. A launch
  option that keeps the game from starting (without `%command%`, or
  pointing at a file that is gone) is listed as a problem.
- The terminal no longer shows the lines `Capturing on '…'` and
  `File: -`, which looked like a file being sent somewhere. Messages
  from the capture program now appear in the status window marked
  `dumpcap on <connection>:`.

## [0.4.0] — 2026-11-09

### Added
- After updating on KDE Plasma 6, run `a2qlinux-setup` once more to make
  two Questlog features work that stayed hidden behind the full-screen game
  on Linux:
  - the **Black Market Cards** overlay, which writes Questlog's notes onto
    the cards of the in-game Black Market shop (your pet's level and souls,
    what an item unlocks or completes, the deals worth taking, how rare an
    item is);
  - moving and resizing overlays with **Alt+E**, which until now showed only
    a brief flash over the game.
  The setup explains the change and asks (Enter means yes); these then show
  while the game is in front and hide when another program is.
  `a2qlinux-setup --no-kde-overlays` takes it back out.
  **Tested and working on KDE Plasma 6.8.2 (Wayland).** Other Plasma 6
  versions may behave differently; on other desktops nothing is changed and
  these two features are not guaranteed to work. If they do not work,
  nothing else is affected.

### Fixed
- **Quit Questlog** in the tray while AION 2 was running froze the game,
  which then had to be ended. The game now keeps running, and Questlog can
  be started again from the menu during play; its meter and Tracker Map
  show the game again after the next zone change.

## [0.3.0] — 2026-11-08

### Added
- Playing through a VPN needs no setting. A2Qlinux listens on all network
  connections at once (cable, Wi-Fi, VPN), and Questlog reads the game on
  whichever one it uses. A VPN changing servers during play is picked up
  within seconds, without a restart.
- When the VPN is switched off during play, the status window and a
  notification say that the game's connection has lost its network and the
  game has to reconnect.
- A warning in the status window and a notification when the game runs
  through a connection that `interface` in the settings file leaves out.
- `interface` can name several connections, as a list:
  `interface = ["eth0", "wg0"]`.

### Changed
- A2Qlinux no longer refuses to start when the computer has more than one
  network connection, for example with a VPN on.
- The status window no longer prints a line every time Questlog reconnects
  to the game traffic, which it does on every zone change. It names the
  connection Questlog follows, once, and again only when that changes;
  problems are still reported as before.

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
