# Changelog

What changed for players, release by release. Technical details are in
`docs/ARCHITECTURE.md`.

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
