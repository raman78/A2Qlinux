# Using Questlog for AION 2 on Linux with A2Qlinux

This guide is for AION 2 players on Linux who want Questlog Desktop, the
Windows-only damage meter and overlay app, running next to the game. It covers
installing Questlog and A2Qlinux, starting them, the tray icon, updating
Questlog, and what to do when something goes wrong. At the end you will have a
"Questlog (AION 2)" entry in your applications menu that opens Questlog,
optionally starting together with the game from Steam.

How it works inside is described in [ARCHITECTURE.md](ARCHITECTURE.md). You do
not need it for daily use.

## The idea in two paragraphs

Questlog reads the game's network traffic through Npcap, a Windows driver that
cannot work on Linux. A2Qlinux captures the traffic on the Linux side with
Wireshark's capture tool and hands it to Questlog through a small replacement
for Npcap's library. Questlog itself is not modified: it runs as on Windows,
inside the same Proton environment as the game, and sees the game the way it
expects to.

Because Questlog and the game then share one Windows environment, A2Qlinux
also takes care of a few things around them. It starts the two in the right
order. It keeps your clicks in the game when Questlog's window is open behind
it. And it shows its own tray icon in place of Questlog's, whose menu does not
work reliably under Proton.

## What you need before you start

- AION 2 from Steam, started at least once, so that its Proton environment
  (the "prefix") exists. It should run in **borderless window** mode, or the
  overlays end up under the game.
- A KDE Plasma desktop. Other desktops may work but have not been tried.
- These packages (names as on Arch / CachyOS):

| Package | What it is for |
|---|---|
| `wireshark-cli` | captures the game's traffic (`dumpcap`) |
| `protontricks` | starts Questlog inside the game's Proton environment |
| `python-pyqt6`, `python-xlib` | the tray icon, bringing Questlog's window to the front |
| `xdotool`, `libnotify`, `konsole` | window activation, notifications, the status window |
| `clang`, `lld`, `wine` | building the small Windows parts of A2Qlinux, once |
| `p7zip` | unpacking Questlog's installer |

- Your user in the `wireshark` group, so that capturing works without
  administrator rights. Run this once, then log out and back in:

```
sudo usermod -aG wireshark $USER
```

Nothing in A2Qlinux is run with `sudo` after that.

## Installing Questlog

Questlog's own installer stops under Proton without installing anything. So
Questlog is installed by unpacking its files into a folder, by default
`~/Games/Questlog`. The same steps are used later to update it.

1. Look up the current version, its file name and its checksum:
   ```
   curl -s https://cdn.questlog.gg/desktop/latest.yml
   ```
   You will see `version`, the installer's file name, `sha512` and `size`.
2. Download that installer into an empty folder (example for 0.1.34):
   ```
   mkdir -p /tmp/qlupd/dl && cd /tmp/qlupd/dl && curl -LO https://cdn.questlog.gg/desktop/questlog-setup-0.1.34.exe
   ```
3. Check the download. The line printed must be identical to the `sha512`
   from step 1:
   ```
   python3 -c "import hashlib,base64,sys;print(base64.b64encode(hashlib.sha512(open(sys.argv[1],'rb').read()).digest()).decode())" questlog-setup-0.1.34.exe
   ```
4. Unpack the installer, then the program package inside it:
   ```
   mkdir -p /tmp/qlupd/nsis /tmp/qlupd/app && cd /tmp/qlupd/nsis && 7z x ../dl/questlog-setup-0.1.34.exe && cd /tmp/qlupd/app && 7z x '/tmp/qlupd/nsis/$PLUGINSDIR/app-64.7z'
   ```
5. Move the program into place:
   ```
   mkdir -p ~/Games/Questlog && cp -a /tmp/qlupd/app/. ~/Games/Questlog/
   ```
6. Delete `/tmp/qlupd`.

Do **not** install Npcap itself into the game's Proton environment. It is a
Windows driver and does not work there. A2Qlinux provides what Questlog needs
instead.

Tip: if you keep Questlog somewhere else, tell A2Qlinux with
`--questlog-dir` when installing (next section).

## Installing A2Qlinux

1. Put the A2Qlinux folder where it will stay. The menu entry points at it,
   so moving it later means running the installer again.
2. In that folder, run:
   ```
   python3 install.py --desktop-shortcut
   ```
   Leave out `--desktop-shortcut` if you only want the menu entry.

The installer checks the packages from the list above and names any that are
missing. It builds the Windows parts the first time and takes Questlog's icon
from your Questlog folder; A2Qlinux does not ship Questlog's logo. Then it
creates the "Questlog (AION 2)" entry. At the end it prints the line for
Steam's launch options (next section) and either "Ready" or a list of what is
still missing. It installs no packages and changes nothing in the game.

## Starting Questlog

There are two ways, and you can use both.

**From the menu or desktop icon.** "Questlog (AION 2)" opens a small terminal
window, A2Qlinux's status window, and then Questlog. This works with or
without the game: without it, you can look through saved fights, the
database and the map. When you start the game later, Questlog picks up the
traffic by itself. Your character appears in Questlog after you log in or
change zone.

**Together with the game, from Steam.** In Steam, open AION 2's Properties >
General > Launch Options and paste the line `install.py` printed. It looks
like this:

```
/path/to/A2Qlinux/steam_launch.sh %command%
```

From then on, Play starts the game first and Questlog a moment later, once
the game runs. If Questlog is already open when you press Play, the game
simply joins it; nothing restarts.

Keep the status window open while you use Questlog. It carries the traffic
to Questlog, and it shows what A2Qlinux is doing. The line
`Game traffic is flowing to Questlog.` means everything is connected. The
window closes by itself when Questlog quits. If something fails, it stays
open with the message until you press Enter.

**When the game ends**, Questlog stays open so you can look at your fights.
Start the game again and the traffic flows to it again. If you would rather
have Questlog close 15 seconds after the game, put `--close-with-game` before
`%command%` in Steam's launch option.

## The tray icon

While Questlog runs, there is one Questlog icon in your system tray. It is
A2Qlinux's own icon; Questlog's original icon is hidden, because under Proton
its menu opens only once and then stops responding.

```
   right-click the icon
   ┌──────────────────────┐
   │  Open Questlog       │
   ├──────────────────────┤
   │  Quit Questlog       │
   └──────────────────────┘
```

| You do | What happens |
|---|---|
| left-click the icon, or **Open Questlog** | Questlog's window opens in front, after about 3 seconds |
| close Questlog's window (X) | the window hides; Questlog keeps running in the background |
| **Quit Questlog** | the icon and window disappear at once; Questlog finishes saving and ends about 12 seconds later; the status window then closes |
| start "Questlog (AION 2)" while Questlog runs | Questlog's window opens; no second copy starts |

**Why quitting takes 12 seconds.** Questlog saves its data every few seconds,
and the only way to end it from outside under Proton skips its last save. So
A2Qlinux hides it first, gives it time to save everything, and only then
ends it. The game is not touched.

**Changed your mind?** If you start "Questlog (AION 2)" from the menu within
those 12 seconds, or press Play in Steam, the quit is called off: the icon
comes back and Questlog keeps running. If it had already ended, a fresh
Questlog starts.

## Using Questlog while you play

- Overlays (the meter, alerts, the tracker map) appear over the game and let
  clicks pass through to it, as on Windows.
- With Questlog's full window open behind the game, clicks in the game stay
  in the game. To work in Questlog's window, switch to it with Alt+Tab, the
  taskbar or the tray icon.
- If you restart Questlog during a play session, the **Tracker Map** overlay
  stays empty until you change zone. That is when Questlog learns where your
  character is.
- Questlog's alerts work in the overlay. Its desktop pop-up notifications do
  not work under Proton.

## Updating Questlog

**A2Qlinux updates Questlog for you.** Questlog's own updater downloads new
versions but cannot install them under Proton (its installer stops, as
described in "Installing Questlog"), so A2Qlinux switches it off and does the
job itself, the way Questlog does on Windows: download in the background,
install at the next start.

What you will notice:

1. A minute after Questlog starts, and every six hours after that, A2Qlinux
   checks for a new Questlog. It never downloads while the game is running,
   so your connection to the game server is left alone; it waits until the
   game is closed.
2. When a new version is out, A2Qlinux downloads it, checks that the
   download is complete and genuine, and checks that the new version still
   works with A2Qlinux. Then you get a desktop notification:
   - "Questlog X is ready. It is installed the next time Questlog starts."
     Nothing else to do.
   - "Questlog X does not fit this A2Qlinux yet …" with the reason. Your
     current version stays. This happens when Questlog changed something
     A2Qlinux relies on; A2Qlinux itself needs an update first.
3. The next time you start "Questlog (AION 2)", the new version is put in
   place before Questlog opens. That takes a few seconds. The status window
   says `Installed Questlog X; Questlog Y is kept in …` and then
   `Starting Questlog X.`
4. If the new version does not start, A2Qlinux puts the previous one back,
   tells you so, and starts it.

The previous version is kept next to the current one (for example
`~/Games/Questlog-0.1.34`) until the next update replaces it. Your fights and
settings are not in these folders, so an update does not touch them.

Tip: the status window shows which version is running in its
`Starting Questlog …` line.

To turn automatic updates off, start A2Qlinux with `--no-auto-update` (in
Steam's launch option, before `%command%`). Then update by hand.

### Updating by hand

1. Do steps 1–4 of "Installing Questlog" for the new version.
2. Check that the new version still works with A2Qlinux. This is a short
   technical check, listed in [ARCHITECTURE.md](ARCHITECTURE.md) §10. If
   you are not comfortable doing it, use the automatic update, which does
   this check for you.
3. Quit Questlog from the tray icon and wait until the status window closes.
4. Swap the folder, keeping the old one and A2Qlinux's working folder
   `proton-stream`:
   ```
   cd ~/Games && mv Questlog Questlog-old && mkdir Questlog && cp -a /tmp/qlupd/app/. Questlog/ && mv Questlog-old/proton-stream Questlog/
   ```
   Replace the whole folder rather than copying over it. Some of Questlog's
   files have changing names, and the old ones would pile up.
5. Start "Questlog (AION 2)". The status window should say
   `Starting Questlog <new version>.`, and the tray should show one icon.
6. If all is well, delete `~/Games/Questlog-old` and `/tmp/qlupd`. If not,
   swap the folders back.

## What can go wrong

| Symptom | Likely cause | What to do |
|---|---|---|
| "No capture bridge: start Questlog with questlog_start.py" in Questlog | Questlog was started some other way | quit it, start "Questlog (AION 2)" |
| "Capture bridge not reachable" | the status window was closed | quit Questlog, start it again from the menu |
| "Capture bridge closed the connection" | A2Qlinux stopped | read the status window, start again |
| "Aion 2's traffic can't be read" before you log in | harmless, it goes away on its own | log in to a server |
| "Questlog is already running in the game prefix without the capture bridge" | a Questlog started outside A2Qlinux is open | quit it from its own tray icon, start again from the menu |
| Steam keeps saying "launching" while Questlog is open | Play was pressed without the launch option | set the Steam launch option; meanwhile A2Qlinux closes Questlog, lets the game start and reopens it |
| two Questlog icons in the tray | hiding Questlog's own icon failed | the status window says why; both icons work, but use A2Qlinux's |
| clicks in the game open Questlog's window | the click fix did not start | look for lines starting `[questlog-proton]` in `~/Games/Questlog/proton-stream/questlog.log` |
| Questlog closes right after starting | its graphics process failed | send `~/Games/Questlog/proton-stream/questlog.log` with your report |
| notification "Questlog X does not fit this A2Qlinux yet" | the new Questlog changed something A2Qlinux relies on | keep using the current version; the reason is in the notification |
| "Questlog update check failed" in the status window | no internet connection at that moment | nothing; it tries again later |
| the menu entry does nothing visible | A2Qlinux is already running and was asked to show Questlog | look for the status window and Questlog's window |

## Removing A2Qlinux

1. Quit Questlog from the tray icon.
2. Clear AION 2's launch options in Steam.
3. Delete the menu entry, the desktop shortcut and the icon:
   ```
   rm ~/.local/share/applications/questlog-aion2.desktop ~/Desktop/questlog-aion2.desktop ~/.local/share/icons/questlog-aion2.png
   ```
4. Delete A2Qlinux's capture library from the game's Proton environment, the
   folder `drive_c/windows/system32/Npcap` inside
   `steamapps/compatdata/3393110/pfx` in your Steam library.
5. Delete the A2Qlinux folder and, if you no longer want Questlog,
   `~/Games/Questlog`. Questlog's fights and settings live in the game's
   Proton environment under `drive_c/users/steamuser/AppData/Roaming/Questlog`.

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
