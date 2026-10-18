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
| Steam keeps saying "launching" while Questlog is open | Play was pressed without the launch option | set the Steam launch option; meanwhile A2Qlinux closes Questlog, lets the game start and reopens it |
| two Questlog icons in the tray | hiding Questlog's own icon failed | the status window says why; both icons work, but use A2Qlinux's |
| clicks in the game open Questlog's window | the click fix did not start | look for lines starting `[a2qlinux]` in `~/Games/Questlog/proton-stream/questlog.log` |
| Questlog closes right after starting | its graphics process failed | send `~/Games/Questlog/proton-stream/questlog.log` with your report |
| notification "Questlog X does not fit this A2Qlinux yet" | the new Questlog changed something A2Qlinux relies on | keep using the current version; the reason is in the notification |
| "Questlog update check failed" in the status window | no internet connection at that moment | nothing; it tries again later |
| the menu entry does nothing visible | A2Qlinux is already running and was asked to show Questlog | look for the status window and Questlog's window |

## FAQ

**Q:** Is this against the game's rules?
**A:** Questlog works the same way as on Windows: it reads a copy of the
network traffic and does not touch the game's files or memory. Whether
third-party meters are allowed is up to the game's publisher; check their
current rules.

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
