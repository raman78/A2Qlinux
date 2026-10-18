# Changelog

What changed for players, release by release. Technical details are in
`docs/ARCHITECTURE.md`.

## [Unreleased]

### Changed
- Quit Questlog ends it at once when no game data is waiting to be saved
  (without the game, or a while after closing it); while playing, it still
  waits until the last data is saved, at most about 10 seconds.

### Fixed
- Steam no longer shows AION 2 as running after the game is closed while
  Questlog stays open: about 15 seconds after the game ends, Questlog restarts
  on its own, as it was (window open or only in the tray), and keeps waiting
  for the next start of the game.

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
