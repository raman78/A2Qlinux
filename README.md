# A2Qlinux

Run [Questlog Desktop](https://questlog.gg/aion-2/en/app), the Windows-only
damage meter and overlay app for AION 2, on Linux next to the game under
Steam's Proton, with live game traffic.

Questlog reads the game's traffic through Npcap, a Windows driver that cannot
work under Wine/Proton. A2Qlinux captures the traffic on the Linux side with
`dumpcap` and hands it to Questlog through its own stand-in for Npcap's
`wpcap.dll`. Questlog runs unmodified, inside the game's Proton prefix, in its
normal live-capture mode, with its overlays over the game.

It also handles what comes with sharing a Wine session with a fullscreen
game:

- starting Questlog before, after or together with the game (Steam launch
  option), without blocking the game's launch;
- keeping clicks in the game while Questlog's window is open behind it;
- its own tray icon (Open / Quit) in place of Questlog's, whose menu opens
  only once under Proton;
- quitting Questlog without losing its last data and without touching the
  game or other programs in the prefix;
- updating Questlog: its own updater cannot install under Proton, so A2Qlinux
  downloads new versions in the background (not while the game runs), checks
  them against what it relies on, installs them at the next start and rolls
  back if they do not start.

Status: in daily use on CachyOS, KDE Plasma 6 (Wayland), Proton 11
(`proton-cachyos-slr`), Questlog 0.1.34. Other setups are untested.

## Quick start

1. Install the requirements and join the `wireshark` group — see
   [docs/MANUAL.md](docs/MANUAL.md#what-you-need-before-you-start).
2. Unpack Questlog to `~/Games/Questlog` — see
   [Installing Questlog](docs/MANUAL.md#installing-questlog).
3. In this folder: `python3 install.py --desktop-shortcut`
4. Start **Questlog (AION 2)** from the menu, or set the Steam launch option
   that `install.py` prints.

## Documentation

- [docs/MANUAL.md](docs/MANUAL.md) — installing, daily use, tray icon,
  updating Questlog, troubleshooting, removal.
- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) — how it works and why, failure
  modes, tests, what a Questlog update can break.

## Repository layout

| Path | What |
|---|---|
| `questlog_start.py` | launcher: capture, bridge, starting/quitting Questlog, tray |
| `pcap_bridge.py` | TCP server that feeds captured packets to the DLL |
| `questlog_desktop.py` | menu-entry and Steam entry point; one launcher at a time |
| `questlog_tray.py` | tray icon (PyQt6) |
| `questlog_update.py` | background Questlog updates: download, verify, check, install, roll back |
| `steam_launch.sh` | Steam launch-option wrapper |
| `install.py` | menu entry, icon, dependency check, build |
| `bridge/` | Windows parts in C: `wpcap.dll` stand-in, `questlog_ctl.exe`, their tests; `build.sh` |
| `tests/` | Python tests: `python3 -m unittest` |
| `tools/` | diagnostics: replay-file tools, TCP-owner probe |

The Windows parts are built with `clang` against the installed Wine's headers
(`bridge/build.sh`, run by `install.py`); built files are not kept in the
repository.

## Not affiliated

A2Qlinux is an independent project, not made or endorsed by Questlog's
authors or by AION 2's publisher. It contains no Questlog code or assets:
Questlog is downloaded from its authors, and its icon is taken from your own
installation. Whether third-party meters are allowed is for the game's
publisher to decide; check their current rules.

## License

MIT — see [LICENSE](LICENSE).
