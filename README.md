# A2Qlinux

Run [Questlog Desktop](https://questlog.gg/aion-2/en/app), the Windows-only
damage meter and overlay app for AION 2, on Linux next to the game under
Steam's Proton, with live game traffic.

Questlog reads the game's traffic through Npcap, a Windows driver that cannot
work under Wine/Proton. A2Qlinux captures the traffic on the Linux side with
`dumpcap` and hands it to Questlog through its own stand-in for Npcap's
`wpcap.dll`. Questlog runs inside the game's Proton prefix, in its normal
live-capture mode, with its overlays over the game. Its program files stay
as shipped; the only change A2Qlinux makes to Questlog's folder is removing
the configuration of Questlog's own updater, which cannot install under
Proton (A2Qlinux updates it instead).

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
(`proton-cachyos-slr`), Questlog 0.1.37. Other distributions and desktops
are untested; what they need (Steam from the distribution or Valve, not
Flatpak; a system tray; Python 3.11 or newer; the packages per distribution)
is in [docs/INSTALL.md](docs/INSTALL.md#what-you-need-before-you-start).

## Quick start

1. Install the requirements and join the `wireshark` group — see
   [docs/INSTALL.md](docs/INSTALL.md#what-you-need-before-you-start).
2. Unpack Questlog to `~/Games/Questlog` — see
   [Installing Questlog](docs/INSTALL.md#installing-questlog).
3. Install A2Qlinux with pipx from the wheel of the newest release, then
   create the menu entry — see
   [Installing A2Qlinux](docs/INSTALL.md#installing-a2qlinux):
   `pipx install ./a2qlinux-<version>-py3-none-any.whl && a2qlinux-setup --desktop-shortcut`
4. Start **Questlog (AION 2)** from the menu, or set the Steam launch option
   that `a2qlinux-setup` prints.

## Documentation

- [docs/INSTALL.md](docs/INSTALL.md) — requirements, installing, removal.
- [docs/USING.md](docs/USING.md) — starting, tray icon, playing.
- [docs/UPDATING.md](docs/UPDATING.md) — Questlog updates.
- [docs/TROUBLESHOOTING.md](docs/TROUBLESHOOTING.md) — problems, FAQ.
- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) — how it works and why, failure
  modes, tests, what a Questlog update can break.

## Repository layout

| Path | What |
|---|---|
| `a2qlinux/launcher.py` | launcher (`a2qlinux-run`): capture, bridge, starting/quitting Questlog, tray |
| `a2qlinux/pcap_bridge.py` | TCP server that feeds captured packets to the DLL |
| `a2qlinux/desktop.py` | `a2qlinux`: menu-entry entry point; one launcher at a time |
| `a2qlinux/tray.py` | tray icon (PyQt6) |
| `a2qlinux/config.py` | settings from `~/.config/a2qlinux/config.toml` |
| `a2qlinux/update.py` | background Questlog updates: download, verify, check, install, roll back |
| `a2qlinux/steam.py` | `a2qlinux-steam`: Steam launch-option wrapper |
| `a2qlinux/setup_desktop.py` | `a2qlinux-setup`: menu entry, icon, dependency check |
| `a2qlinux/bin/` | the built Windows parts (shipped in the package, not in git) |
| `bridge/` | Windows parts in C: `wpcap.dll` stand-in, `questlog_ctl.exe`, their tests; `build.sh` |
| `tests/` | Python tests: `python3 -m unittest` |
| `tools/` | diagnostics: replay-file tools, TCP-owner probe |

The Windows parts are built with `clang` against the installed Wine's headers
(`bridge/build.sh`) — by the release workflow for the packages, by hand in a
source checkout; built files are not kept in the repository. Releasing:
[docs/RELEASE.md](docs/RELEASE.md).

## Not affiliated

A2Qlinux is an independent project, not made or endorsed by Questlog's
authors or by AION 2's publisher. It contains no Questlog code or assets:
Questlog is downloaded from its authors, and its icon is taken from your own
installation. Questlog and its name belong to its authors (questlog.gg).

Whether third-party meters are allowed is for the game's publisher, NCSOFT,
to decide. It has not said so either way, and its rules forbid
"unauthorized programs" in general terms. Using any third-party meter,
under Windows or through A2Qlinux, is at your own risk; check the
publisher's current rules.

## License

MIT — see [LICENSE](LICENSE).
