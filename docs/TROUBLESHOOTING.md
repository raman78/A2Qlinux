# When something goes wrong

This page lists the messages and symptoms you may meet with Questlog under
A2Qlinux, what causes them and what to do, followed by common questions.

## What can go wrong

| Symptom | Likely cause | What to do |
|---|---|---|
| "No capture bridge: start Questlog with A2Qlinux" in Questlog | Questlog was started some other way | quit it, start "Questlog (AION 2)" |
| "Capture bridge not reachable" | the status window was closed | quit Questlog, start it again from the menu |
| "Capture bridge closed the connection" | A2Qlinux stopped | read the status window, start again |
| "Aion 2's traffic can't be read" before you log in | harmless, it goes away on its own | log in to a server |
| "Questlog is already running in the game prefix without the capture bridge" | a Questlog started outside A2Qlinux is open | quit it from its own tray icon, start again from the menu |
| "Settings: … line N …" in the status window, or a notification about the settings file | a mistake in `~/.config/a2qlinux/config.toml` | fix that line; until then the setting keeps its default |
| Steam shows AION 2 as running after you closed it | a program the game started is still ending, or the game was started before Questlog and Questlog restarts about 10 seconds after the game; or another Windows program started in the game's environment still runs | wait 30 seconds; the status window says what it ended or which program holds the game; Stop in Steam is safe, it does not touch Questlog |
| Steam keeps saying "launching" while Questlog is open | Play was pressed without the launch option | set the Steam launch option; meanwhile A2Qlinux closes Questlog, lets the game start and reopens it |
| two Questlog icons in the tray | hiding Questlog's own icon failed | the status window says why; both icons work, but use A2Qlinux's |
| clicks in the game open Questlog's window | the click fix did not start | look for lines starting `[a2qlinux]` in `~/Games/Questlog/proton-stream/questlog.log` |
| Questlog closes right after starting | its graphics process failed | send `~/Games/Questlog/proton-stream/questlog.log` with your report |
| notification "Questlog X does not fit this A2Qlinux yet" | the new Questlog changed something A2Qlinux relies on | keep using the current version; the reason is in the notification |
| "Questlog update check failed" in the status window | no internet connection at that moment | nothing; it tries again later |
| the menu entry does nothing visible | A2Qlinux is already running and was asked to show Questlog | look for the status window and Questlog's window |
| notification "No terminal for the status window was found" | none of the terminals A2Qlinux knows is installed | install one of those the notification names, for example `xterm` |
| "Several interfaces are up (…); choose one with --interface" | the computer has more than one network connection: Wi-Fi and cable, a VPN, Docker or virtual machines | set `interface` in the settings file ("Settings" in [USING.md](USING.md)) to the one the game uses; `ip route get 1.1.1.1` names it after `dev` |
| "AION 2's Wine prefix was not found in Steam's libraries" | the game has not been started from Steam yet, or Steam is somewhere A2Qlinux does not look | start the game once from Steam; the message lists where A2Qlinux looked |
| "Only a Flatpak Steam was found" | Steam is installed from Flatpak | install Steam from your distribution or from Valve instead (see [INSTALL.md](INSTALL.md#what-you-need-before-you-start)) |
| "requires a different Python" when installing with pipx | your Python is older than 3.11 | use a newer distribution release (see [INSTALL.md](INSTALL.md#what-you-need-before-you-start)) |
| "dumpcap stopped. Check capture permission" | you are not yet allowed to capture: not in the `wireshark` group, not logged in again since, or on Debian and Ubuntu capturing is not allowed for the group | run `a2qlinux-setup`: it tries a capture and prints the commands still needed (see "Allowing capture" in [INSTALL.md](INSTALL.md#allowing-capture)) |
| `a2qlinux-setup`: "… already exists and is not an empty folder, but holds no Questlog.exe" | the Questlog folder holds something else, so A2Qlinux does not install into it | move that folder away, or give another one with `--questlog-dir` |
| `a2qlinux-setup`: "Questlog's download information could not be read" or "Questlog X could not be installed" | no internet connection, or the download broke off | run `a2qlinux-setup` again; nothing half-installed is left behind |
| `a2qlinux-setup`: "Questlog X does not fit this A2Qlinux yet" | the newest Questlog changed something A2Qlinux relies on | update A2Qlinux (`pipx upgrade a2qlinux`); if there is no newer A2Qlinux yet, install an earlier Questlog by hand ([UPDATING.md](UPDATING.md#installing-questlog-by-hand)) |
| `a2qlinux-setup` says the tray icon cannot run | see below | see below |

## The tray icon

A2Qlinux shows Questlog's icon in your desktop's system tray; its menu has
Open Questlog and Quit Questlog. `a2qlinux-setup` checks that the icon can
run and prints what stands in the way:

| What it prints | What to do |
|---|---|
| "the desktop has no system tray" | on GNOME, install and switch on the extension "AppIndicator and KStatusNotifierItem Support" (package `gnome-shell-extension-appindicator` on Debian, Ubuntu and Fedora), then log out and in; on other desktops, add the system tray to the panel |
| "xcb-cursor0 or libxcb-cursor0 is needed" | install `libxcb-cursor0` (Debian, Ubuntu, openSUSE) or `xcb-util-cursor` (Fedora, Arch) |
| another message starting with `qt.qpa` | a part of the desktop's graphics libraries is missing; the message names it |

Without a working tray icon, A2Qlinux shows Questlog's own Windows tray
icon instead, which needs a system tray too, and whose menu opens only once
under Proton. Closing the status window does not quit Questlog either; it
only stops the live traffic. So get the tray icon working before you play.

## FAQ

**Q:** Is this against the game's rules?
**A:** Questlog works the same way as on Windows: it reads a copy of the
network traffic and does not touch the game's files or memory. Whether
third-party meters are allowed is up to the game's publisher, NCSOFT. It
has not said so either way, and its rules forbid "unauthorized programs" in
general terms. Using any third-party meter is at your own risk; check the
publisher's current rules.

**Q:** Does it slow the game down?
**A:** Measured with the game running, Questlog and A2Qlinux together used
about a tenth of one CPU core and about 40 MB of graphics memory.
Questlog shows events about 0.1–0.2 seconds after they happen.

**Q:** Can I use another meter, such as NotMeter, at the same time?
**A:** A2Qlinux leaves other programs in the game's Proton environment
alone. Running both at once has not been tried.

**Q:** Is A2Qlinux made by Questlog's authors?
**A:** No. It is an independent project. Questlog is © its authors and is
not included here.
