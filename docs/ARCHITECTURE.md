# A2Qlinux — architecture

How A2Qlinux runs Questlog Desktop (a closed-source, Windows-only Electron
combat meter for AION 2) under Proton on Linux: what each part does, in what
order, and why it is shaped that way. Daily use is in `docs/MANUAL.md`; this
document is for changing or debugging the code.

Measured on CachyOS, KDE Plasma 6 on Wayland (X11 programs through XWayland),
Steam with `proton-cachyos-slr` (Proton 11), Questlog 0.1.34 (Electron 44.5.1),
in October 2026.

## 1. Purpose

Questlog reads the game's network traffic through Npcap's
`C:\Windows\System32\Npcap\wpcap.dll`. Npcap is a Windows kernel driver and
cannot run under Wine. A2Qlinux replaces that one DLL with its own
`wpcap.dll`. The replacement implements the eleven libpcap calls Questlog
makes and feeds them packets captured on the Linux side. With it, Questlog
runs its normal live-capture code path, unmodified, inside the game's Proton
prefix.

Everything else in this repository exists because Questlog then shares a
Wine session with a fullscreen game: starting the two in the right order,
keeping clicks in the game, replacing a tray menu that Wine breaks, and
quitting Questlog without disturbing the game.

Terms used below:

- **prefix** — the game's Wine prefix, `compatdata/3393110/pfx` in the Steam
  library (3393110 is AION 2's Steam app id, `APPID`).
- **Wine session** — the set of Windows processes served by one `wineserver`.
  Questlog has to be in the game's session: it finds the game's connection
  with `GetExtendedTcpTable` and positions its overlays from the game window.
- **launcher** — `questlog_start.py`, which runs for as long as Questlog runs.
- **bridge** — the TCP link from the launcher (`BridgeServer` in
  `pcap_bridge.py`) to our `wpcap.dll` inside Questlog.

## 2. Context

```
 Linux, normal user                           Proton prefix 3393110
 +-------------------------------------+     +-------------------------------+
 | questlog_start.py  (launcher)       |     | AION2.exe                     |
 |  +- dumpcap (TCP port 13328)        |     |                               |
 |  |   +- BridgeServer 127.0.0.1:port +---->| Questlog.exe --no-sandbox     |
 |  |      (pcap_bridge.py, token)     | TCP |  +- wpcap.dll (ours, in       |
 |  +- Tray -> questlog_tray.py (KDE)  |     |  |   System32\Npcap)           |
 |  +- protontricks-launch ------------+---->|  |   pcap_next_ex every 25 ms |
 |  +- protontricks-launch ------------+---->|  +- window-order guard thread |
 |       questlog_ctl.exe <command>    |     | questlog_ctl.exe (short-lived)|
 +-------------------------------------+     +-------------------------------+
        ^ SIGUSR1 / SIGUSR2
        |
 questlog_desktop.py  <- menu entry, desktop icon, steam_launch.sh
```

| Program | Runs where | Role |
|---|---|---|
| `questlog_start.py` | Linux | launcher: capture, bridge, starting and quitting Questlog, tray |
| `pcap_bridge.py` | Linux, in the launcher | `BridgeServer`: hands captured packets to every connected DLL |
| `questlog_desktop.py` | Linux | entry point of the menu entry and of `steam_launch.sh`; one launcher at a time |
| `questlog_tray.py` | Linux, child of the launcher | our tray icon (PyQt6, drawn by KDE) |
| `steam_launch.sh` | Linux, as Steam's launch option | starts the launcher with the game; lets the game join a running Questlog |
| `questlog_update.py` | Linux, in the launcher | stages new Questlog versions in the background, installs them at the next start (§6.6) |
| `install.py` | Linux, by hand | menu entry, icon, dependency check, build |
| `bridge/wpcap.dll` | prefix, in Questlog's NodeService process | libpcap stand-in; window-order guard |
| `bridge/questlog_ctl.exe` | prefix, started per command | hides/shows Questlog's tray icon, closes its window, ends its session |

## 3. Invariants

- **I1 — one launcher.** `session_lock` holds an exclusive `flock` on
  `<Questlog dir>/proton-stream/.lock` for the launcher's lifetime and writes
  its PID into the file. A second launcher would start a second bridge, while
  its Questlog launch would hand over to the running Questlog on the first
  bridge.
- **I2 — Questlog only.** Nothing A2Qlinux does acts on other programs in the
  prefix (the game, other meters such as NotMeter). Per-object Windows calls
  (one icon, one window) are used instead of prefix- or session-wide switches.
  The one exception, `wineboot -e` in `close_questlog`, runs only when the
  game has been gone for `GAME_EXIT_GRACE` seconds (see §6.4).
- **I3 — nothing dropped silently.** Each failure of the bridge, the guard,
  `questlog_ctl.exe` or the tray is reported: to Questlog's interface (DLL
  errors through `pcap_geterr`), to the launcher's terminal, or to
  `proton-stream/questlog.log`.
- **I4 — no traffic on disk.** The capture flows through memory only. The
  bridge token keeps other local programs from reading it (the traffic
  includes chat).

## 4. Data flow: capture

1. `questlog_start.py` takes the lock (I1), checks that `dumpcap` is the
   distribution's root-owned binary (`system_dumpcap`), and chooses the
   network interface: the only one besides `lo` with an IPv4 address, or
   `--interface`.
2. It starts `BridgeServer` on `127.0.0.1` with a random port and token, and
   `dumpcap -F pcap` filtered to `tcp and host <address> and port 13328`.
   A thread (`pump_records`) passes each record to `BridgeServer.publish`.
3. It finds the prefix (`game_prefix`): from a running `AION2.exe`'s
   environment, else from Steam's `libraryfolders.vdf`. Then it installs
   `bridge/wpcap.dll` as `drive_c/windows/system32/Npcap/wpcap.dll`
   (`install_bridge_dll`). It replaces only an empty marker or an older build
   of ours, recognised by the string `questlog-proton bridge`
   (`BRIDGE_SIGNATURE`). Any other file there, such as a real Npcap, is left
   alone and reported.
4. It starts Questlog in the prefix through `protontricks-launch`
   (`launch_questlog`), with:
   - `QUESTLOG_PROTON_BRIDGE=127.0.0.1:<port>:<token>:<interface address>`,
     read by the DLL;
   - `WINEDLLOVERRIDES=wpcap=n`, because Wine ships a builtin `wpcap` and
     loads it instead of a native file of that name, even when Questlog
     names our file by full path;
   - `--no-sandbox`, explained in §7.1.
5. Questlog finds the game's TCP connection itself (`GetExtendedTcpTable`;
   Wine reports connection owners correctly, as checked with
   `tools/tcp_owner_probe.c`). It picks the device whose address matches the
   connection and opens it. `pcap_open_live` in our DLL connects to the
   bridge, sends `QLPB1 <token>` and receives a pcap file header.
6. Every 25 ms Questlog calls `pcap_next_ex` until it returns 0 and
   reassembles the TCP streams itself. Packet times come from the record
   headers, i.e. from when `dumpcap` captured them. `dumpcap` writes
   nanosecond timestamps; the server converts them to microseconds, which is
   what Questlog reads.
7. On a zone change Questlog opens a new device before closing the old one.
   The server serves any number of connections, each with every packet. A
   connection that stops reading (`CLIENT_QUEUE_RECORDS`, 5000 records
   queued) is dropped with a message; Questlog reopens it within a second.

### 4.1 The DLL's calls

| Call | Behaviour |
|---|---|
| `pcap_findalldevs` | one device carrying the address from `QUESTLOG_PROTON_BRIDGE`; without that variable, the error "No capture bridge: start Questlog with questlog_start.py", which Questlog shows |
| `pcap_open_live` | connect to the bridge, authenticate, read the pcap header |
| `pcap_next_ex` | 1 = packet, 0 = none waiting (non-blocking), -1 = connection lost, reason in `pcap_geterr` |
| `pcap_compile`, `pcap_setfilter`, `pcap_freecode` | accepted, no effect; `dumpcap` already filters |
| `pcap_setnonblock`, `pcap_datalink`, `pcap_geterr`, `pcap_close`, `pcap_freealldevs`, `pcap_lib_version` | as in libpcap |

The first call to `pcap_findalldevs` or `pcap_open_live` also starts the
window-order guard (§6.1).

### 4.2 Latency and load

With the game (16 October 2026), Questlog saved four boss kills
0.12–0.21 s after the kill, and the delay did not grow over the session.
In an integration test (live `dumpcap` → server → DLL under Proton → a client
calling the DLL as Questlog does), the mean was 136 ms and the maximum 270 ms.
About 125 ms of that is `dumpcap`, which hands packets over in batches at most
every 250 ms; `-N`, `-C` and `--update-interval` do not change that
(measured). The bridge and DLL add about 10 ms.

**Measuring it from Questlog's own data:** an encounter that ends in a kill
(`end: "kill"` in `encounters/index.json` under Questlog's data folder) is
saved the moment Questlog processes the packet with the boss's death. So
`savedAt` minus (`startedAt` + `durationSeconds`) is the processing delay.
Look at the trend over a session, not at one fight. Encounters that end
without a kill close only after 15 s without hits, so they do not measure
anything.

Load over 30 s with the game running (Ryzen 7 7700X, RTX 3060 Ti): Questlog's
nine processes 0.07 of a core and 37 MB of GPU memory; the shared
`wineserver` 0.04; the launcher 0.01; `dumpcap` about 0. `dumpcap` reads a
copy of the traffic and does not affect the connection to the game server.

## 5. Starting Questlog and the game in one Wine session

### 5.1 Proton waits for an idle prefix

Steam starts the game as `proton waitforexitandrun …AION2.exe`. In Proton's
`proton` script, `waitforexitandrun` first runs `wineserver -w`, i.e. waits
until nothing runs in the prefix. A Questlog started before the game keeps
the prefix busy, so the game would wait for as long as Questlog runs. Steam
then shows "launching" with no end.

`steam_launch.sh`, set as the game's Steam launch option, handles this:

1. It records whether a launcher holds the lock **before** starting anything.
2. It starts `questlog_desktop.py --wait-for-game` through
   `systemd-run --user`. Started that way, the launcher and its terminal get
   the desktop session's environment instead of Steam's (overlay
   `LD_PRELOAD`, container variables), and Steam does not count them as part
   of the game. If this fails, the game still starts, with a notification.
3. If a launcher was running, it replaces only Proton's own verb
   `waitforexitandrun` with `run`. `run` sets up drive letters for the game
   and Steam folders and starts the game without waiting, so the game joins
   Questlog's session. The runtime container keeps
   `--verb=waitforexitandrun`, which marks it as the game's main container.
   Each switch is logged to `proton-stream/steam_launch.log`.

Checked with the game (17 October 2026): Questlog opened without the game,
then Play. The game started at once, with one `wineserver` shared by both.

### 5.2 Fallback without the launch option

When Play is pressed without `steam_launch.sh`, the launcher sees a pending
launch (`steam_launch_pending`). It looks for Proton's own process,
`python3 …/proton waitforexitandrun …AION2.exe`, with the game's app id in
its environment, while no `AION2.exe` runs yet. It then closes Questlog
(`close_questlog`), waits for the game (`wait_for_game_or_cancel`) and starts
Questlog again on the same bridge. If Steam gives up (10 s with no pending
launch), Questlog comes back without the game.

Only Proton's process counts, in exactly that shape. An earlier version
matched any process whose command line contained `waitforexitandrun`. Steam
runs the launch option first in the chain, so `steam_launch.sh` itself
briefly carried the original command line. That version sent `wineboot -e`
into the session where the game was starting, which closed Questlog and
aborted the game.

### 5.3 `--wait-for-game`

With `--wait-for-game` (always used by `steam_launch.sh`), the launcher
starts Questlog only once `AION2.exe` has run for 2 s (`wait_for_game`). This
way the game and Questlog never bring up the prefix's Wine at the same
moment.

## 6. Living with the game in one session

### 6.1 Window-order guard (clicks reaching Questlog)

**Symptom.** With Questlog's main window open behind the game, an Alt+click
in the game activates Questlog, which jumps above the game. With Questlog
hidden in the tray it does not happen.

**Cause** (traced with `WINEDEBUG=+event,+x11drv,+win` and read in Proton 11's
source):

- While the game is in the foreground it confines the cursor (`ClipCursor`).
  `winex11.drv` implements that by grabbing the pointer with one clip window
  per Wine session (`grab_clipping_window`). This is an InputOnly X window
  covering the screen, above the game, owned by the session's desktop process.
- A click on the clip window has no Windows target. `send_mouse_input` passes
  it on with no window, and `wineserver` picks the window under the cursor
  from **its own** z-order (`shallow_window_from_point` in `server/queue.c`).
- Wine's z-order is not updated when the window manager raises the game. So
  Questlog's main window, the last one active, is still above the game in
  that order. Questlog receives the click and Chromium activates the window.
- A window hidden to the tray is invisible to Wine and is skipped.
- Proton 11 no longer has the `GrabPointer` registry option that used to
  turn the grab off.

Evidence in the trace: `set_foreground_window hwnd <Questlog window>,
mouse 1` with no X button event in Questlog's process; pointer motion from
the screen centre, where the game holds the cursor, routed to Questlog's
window.

**What the guard does** (`start_window_guard`, `guard_once` in
`bridge/wpcap_bridge.c`): every `GUARD_INTERVAL_MS` (50 ms) it reads the
foreground window. If that window belongs to a program other than Questlog,
the guard walks up the z-order from it. Every ordinary Questlog window above
it is moved directly below it with
`SetWindowPos(…, SWP_NOACTIVATE | SWP_NOMOVE | SWP_NOSIZE | SWP_NOOWNERZORDER)`.
Wine's order then matches the screen, clicks go to the game, and Questlog
reacts only once switched to (Alt+Tab, the taskbar).

- *Which windows are Questlog's:* recognised by program image, not by
  process. The DLL is loaded by Questlog's NodeService utility process,
  while the windows belong to its browser process.
- *Which are left alone:* topmost windows and `WS_EX_NOACTIVATE` windows.
  Questlog's overlay windows have extended style `0x8080020` (non-activatable,
  layered, transparent to clicks) and are ordered by Questlog itself; the
  main window has `0x100`.
- *Logging (I3):* each move is written to stderr, which ends up in
  `proton-stream/questlog.log`:
  `[questlog-proton] Questlog window … moved it below.` A failed move is
  logged once per window and error code; a guard that cannot start says so.

Tested with `bridge/tests/zorder_guard_test.c` (§9): passes with the guard,
fails with it disabled. With the game: the click stays in the game, switching
to Questlog and back works, the overlays stay visible.

**Trade-off.** The defect is Proton's. The right fix would update Wine's
z-order when the window manager activates a window, or route clip-window
clicks to the clip owner. The guard compensates from our side because a
patched Proton would have to be rebuilt on every update. The game's window is
not touched, only Questlog's. Wine's desktop process (`explorer.exe`) is
briefly the foreground window after a tray click, and the guard then moves
Questlog below it too; no visible effect was seen.

### 6.2 Tray icon replacement

**Symptom.** Right-click on Questlog's tray icon: the menu opens. After
clicking anything else, the next right-click shows nothing.

**Cause** (trace and source):

1. The click goes from KDE through `xembedsniproxy` to the icon window of
   the session's `explorer.exe`, which relays only a notification to
   Questlog (`notify_owner` in `programs/explorer/systray.c`).
2. Before opening the menu, Electron calls `SetForegroundWindow` on its
   hidden icon window. If that fails, it gives up without a word
   (`NotifyIcon::PopUpContextMenu`).
3. `wineserver` refuses `SetForegroundWindow` to a process that is not in
   the foreground and did not receive the latest user input
   (`DECL_HANDLER(set_foreground_window)`). The latest input went to
   `explorer.exe`.
4. The first call for each window is let through unchecked
   (`make_window_foreground`, the `set_foreground` flag). That is why the
   menu works once.

On Windows the shell lets the icon's owner take the foreground. Wine's
`AllowSetForegroundWindow` does nothing and `explorer.exe` grants nothing,
upstream Wine included. Trace: `set_foreground_window hwnd <icon window> …
-> ret 1` for the first menu, `-> ret 0` for the next.

**Replacement.** The launcher shows its own icon instead
(`questlog_tray.py`, `QSystemTrayIcon`, which KDE serves as a
StatusNotifierItem). Its menu is drawn by KDE, outside Wine's foreground
rules. The tray process only prints `open` or `quit` on stdout; class `Tray`
in `questlog_start.py` reads that into `Requests`. The tray runs in its own
session, so a Ctrl+C for the launcher does not reach it. It ends when its
stdin closes.

Questlog's own icon is hidden with `questlog_ctl.exe hide-tray`
(`set_tray_hidden`): `Shell_NotifyIconW(NIM_MODIFY)` with
`NIS_HIDDEN`, addressed by the icon's owner window (class
`Electron_NotifyIconHostWindow`) and id 3 (`ICON_ID`). Electron gives its
first icon `kBaseIconId` (2) + `next_icon_id_` (starts at 1) in
`notify_icon_host.cc`. This hides that one icon only (I2). The prefix-wide
`NoTrayItemsDisplay` policy was rejected because it would hide NotMeter's
icon too. Electron's later `NIM_MODIFY` calls do not touch the hidden state.
Only a full re-add (after `explorer.exe` restarts, `TaskbarCreated`) would
show it again.

`hide_questlog_tray_icon` runs `hide-tray` only once Questlog's processes
exist. Two `protontricks-launch` calls starting together while no Wine
session is up can bring up two separate sessions, and `questlog_ctl.exe`
would then look for the icon where Questlog does not run. That happened once,
before this ordering was added. `hide-tray` itself waits up to 60 s
(`HIDE_TRAY_WAIT_MS`) for the icon to be added.

If the tray process ends by itself, or the launcher ends while Questlog runs
(Ctrl+C, an error), the launcher runs `show-tray` so that Questlog can always
be quit (I3).

### 6.3 Opening Questlog's window

Left click or "Open Questlog" runs `show_questlog_window`. It starts Questlog
a second time with the same launch command. Questlog's `second-instance`
handler shows the running copy's main window, and the second copy exits.
Wine does not let Questlog take the focus (same rule as §6.2), so
`activate_questlog_window` then finds the window in `_NET_CLIENT_LIST` by
title `Questlog` and a `_NET_WM_PID` that is one of Questlog's processes.
It asks KWin to activate it (`xdotool windowactivate`, i.e.
`_NET_ACTIVE_WINDOW`). This takes about 3 s, most of it `protontricks-launch`.

### 6.4 Quitting Questlog

Questlog's only clean quit is its own tray menu's Quit (`app.quit()`). From
outside, the only way to end it is a Windows session end. Electron 44 handles
`WM_ENDSESSION` in `native_window_views_win.cc` by emitting `session-end` and
then calling `TerminateCurrentProcessImmediately`, skipping its normal quit,
where Questlog flushes pending data. Questlog writes that data on its own at
most 10 s after it changes: the combat worker flushes every 10 s, and
deferred saves wait 10 s.

So "Quit Questlog" in our tray (`QuitControl` in `questlog_start.py`) works
in two stages:

```
 "quit" ---> tray-off, close-window (Questlog hides; keeps running)
               |
               |  SAVE_WAIT = 12 s
               v
             questlog_ctl.exe end-session      (WM_QUERYENDSESSION,
               |                                 WM_ENDSESSION -> its main
               v                                 window only)
             wait_for_questlog_exit (QUESTLOG_QUIT_WAIT = 20 s, then SIGTERM)
               |
               +-- an "open"/"keep" arrived meanwhile --> start Questlog again
               +-- otherwise --> launcher ends
```

- `close-window` posts `WM_CLOSE` to the main window, which Questlog answers
  by hiding to the background.
- `end-session` goes to Questlog's main window only. The game and other
  programs receive nothing (I2), unlike `wineboot -e`, which ends every
  program in the session.
- Measured in the prefix and in a throwaway prefix: Questlog and all its
  processes are gone about 0.1 s after `end-session`.
- An "open" (`SIGUSR1`, tray) or "keep" (`SIGUSR2`, Steam) during the 12 s
  calls the quit off: the tray comes back, and for "open" the window is
  shown. Once `end-session` has been sent, such a request makes the launcher
  start Questlog again on the same bridge after it has gone.

`--close-with-game` uses `close_questlog` instead: `wineboot -e` 15 s
(`GAME_EXIT_GRACE`) after `AION2.exe` has gone, by which time nothing is left
but Questlog. It was written before `questlog_ctl.exe` existed and is kept for
that case. `wineboot -e` must never be sent while the game runs or is
starting (§5.2).

Electron's auto-update would install on quit (`autoInstallOnAppQuit`); it is
switched off (§6.6), and the session end would skip it anyway.

### 6.5 Signals between the menu entry and the launcher

`questlog_desktop.py` is what the menu entry, the desktop icon and
`steam_launch.sh` run. If no launcher holds the lock, it opens Konsole with
`questlog_start.py`. Otherwise it signals the PID read from the lock file
(`launcher_pid`), after checking that the process's command line is
`questlog_start.py`, so a stale or reused PID is never signalled:

| Caller | Signal | Launcher's response |
|---|---|---|
| menu entry, desktop icon | `SIGUSR1` | show Questlog's window; call off a pending quit |
| `steam_launch.sh` (`--wait-for-game`) | `SIGUSR2` | keep Questlog running; call off a pending quit; no window |

The handlers are installed before the PID is published, since the default
action of both signals would end the launcher. Handlers and the tray reader
thread only append to `Requests` (a `deque`, whose `append` takes no lock a
signal could interrupt). The main loop drains it every 0.5 s. If the launcher
was ending when signalled, it releases the lock instead of answering; the
menu entry waits up to `HANDOVER_WAIT` (10 s) for that and then starts a new
launcher.

### 6.6 Updating Questlog

Questlog updates itself with electron-updater: every 5 minutes it reads
`https://cdn.questlog.gg/desktop/latest.yml`, downloads a newer installer in
the background, and runs it on quit or from an "install" button in its
window. Under Wine that installer stops (§7.5), so a downloaded update is
never installed. `questlog_update.py` does the update instead, the same way as
a manual update, which therefore remains the fallback (`docs/MANUAL.md`,
"Updating Questlog"):

```
 launcher start ── disable_builtin_updater ── install_staged ── Questlog runs
                                                   ^                  |
                                                   |   60 s, then every 6 h,
                                                   |   deferred while AION2.exe runs
                                                   |                  v
           <state>/update/<version>/app  <──── stage(): feed -> download ->
           <state>/update/staged.json           size + SHA-512 -> 7z -> checks
```

1. **`disable_builtin_updater`** removes `resources/app-update.yml`, the only
   configuration electron-updater runs on. Questlog then logs
   `[updater] … ENOENT … app-update.yml` every 5 minutes and does nothing
   else: it downloads nothing and never shows its "update ready" prompt,
   which appears only after a download. Tested in a throwaway prefix.
2. **`stage`**, in a thread (`check_for_updates` in `questlog_start.py`): first
   check 60 s after the start, then every `UPDATE_CHECK_EVERY` (6 h). While
   `AION2.exe` runs it waits instead (`UPDATE_CHECK_DEFER`, 10 min), so the
   115 MB download never competes with the game's connection. It reads the
   feed (`parse_feed`) and compares versions numerically. For a newer
   version it downloads the installer with the User-Agent
   `A2Qlinux (Questlog updater for Linux)`; the CDN answers Python's default
   one with 403. It checks the size and SHA-512 against the feed, unpacks
   the NSIS installer and its `$PLUGINSDIR/app-64.7z` with `7z`, and runs
   `compatibility_problems`, which automates the checks of §10.
   - Fits: the version is left staged, and the user is told it installs at
     the next start (log and desktop notification).
   - Does not fit: the unpacked files are deleted, and the user is told which
     check failed and that the installed version stays.
   - Either way the verdict is kept in `staged.json`, so the same version is
     not downloaded again.
3. **`install_staged`**, called by `start_questlog` before every Questlog
   launch: if a version that fits is staged, the Questlog folder is renamed
   to `<folder>-<old version>`, the staged files take its place, and
   `proton-stream` moves across. The launcher's lock is an open file and
   moves with it, so it stays held. One backup is kept: the previous one
   made by A2Qlinux is deleted, recorded in `proton-stream/questlog-backup.json`.
   Folders A2Qlinux did not make are never deleted.
4. **Trial:** if the just-installed Questlog ends within `UPDATE_TRIAL`
   (60 s) of its start, `rollback` puts the backup back, marks the version as
   not fitting, notifies the user and starts the previous version.

A busy lock (`BUSY`) keeps an install from meeting a half-written stage; an
install that finds a stage in progress waits for a later start.
`--no-auto-update` turns off steps 2–4. Step 1 stays, since the built-in
updater cannot install under Wine anyway.

**Why "at the next start".** That is when Questlog does not run, so the swap
needs no shutdown; it is also what Questlog does on Windows. A swap while
Questlog runs would mean ending it in the middle of a session.

**Why an unknown Electron version blocks the install.** The tray icon id and
the `WM_ENDSESSION` behaviour that `questlog_ctl.exe` relies on cannot be
read from the binary, only from Electron's source for that version. A new
Electron is reported to the user instead; adding it to `KNOWN_ELECTRON`
after reading that source lets the next check install it.

Checked against the real CDN (18 October 2026), on a copy of 0.1.29: feed,
download, checksum, unpacking, checks and swap to 0.1.34 in 3.9 s. The result
was identical to the manual installation of the same version, except for the
removed `app-update.yml`.

## 7. Failure modes

| Symptom | Cause | Where to look |
|---|---|---|
| Questlog quits at once, "GPU process isn't usable" | Chromium's sandbox inside Steam's container (§7.1) | `questlog.log` |
| Questlog shows "No capture bridge: start Questlog with questlog_start.py" | Questlog started without the launcher | start it from the menu entry |
| "Capture bridge not reachable (is questlog_start.py running?)" | launcher not running (terminal closed) | Konsole window |
| "Capture bridge closed the connection …" | launcher stopped, or it dropped a connection | Konsole window |
| Steam "launching" forever while Questlog runs | Proton waiting for an idle prefix (§5.1) | `steam_launch.log`; set the launch option |
| click in the game activates Questlog | §6.1; guard not running | `questlog.log`, `[questlog-proton]` lines |
| two Questlog tray icons | `hide-tray` failed | Konsole window, `Questlog control:` lines |
| "Aion 2's traffic can't be read" before logging in | §7.3, harmless | — |
| "questlog_start.py is already running in another window" | second launcher refused (I1) | use the running one |
| "Questlog is already running in the game prefix without the capture bridge" | Questlog started outside A2Qlinux | quit it from its own tray icon |
| Tracker Map overlay blank after restarting Questlog mid-game | Questlog learns the character's zone only at login or zone change | change zone |
| "Questlog update check failed (…)" | no network, CDN change | none; retried at the next check |
| "Questlog X does not fit this A2Qlinux yet …" (notification) | a check of §10 failed | A2Qlinux needs a change for that version; the installed one stays |
| "Questlog X ended within 60 s … going back" | the new version did not start under Proton | the previous version runs again; the failed one is in `<folder>-X-failed` |

### 7.1 `--no-sandbox`

In the prefix, Questlog runs inside Steam's runtime container
(pressure-vessel), where Chromium cannot set up its Windows sandbox: the GPU
process exits with error 39 and renderers fail with
`ERR_FAILED loading app://questlog/…`. Outside the container there was no
problem. `--disable-gpu-sandbox` alone fixes the GPU process only.
`--no-sandbox` costs page isolation, which Wine weakens anyway because it
does not enforce the Windows security boundaries the sandbox relies on.

### 7.2 `wpcap.dll` and Questlog's Npcap warnings

Questlog warns "Npcap is not installed" when
`C:\Windows\System32\Npcap\wpcap.dll` is missing. It warns "not running" only
when a stopped `npcap` service exists, and "admin-only" only with an
`AdminOnly` registry value. With our DLL none of these appear. A real Npcap
must not be installed in the prefix; it is a kernel driver. The game's
anti-cheat (NCGuard) can see the `Npcap` folder, as on every Windows machine
with Questlog; how it judges that is unknown. To remove it, delete
`drive_c/windows/system32/Npcap/` in the prefix.

### 7.3 "Aion 2's traffic can't be read" before logging in

Questlog watches every TCP connection of the game process, including local
ones to `127.0.0.1` (Steam). For those it looks for a loopback device, which
our DLL does not report, and records a problem. The warning appears only
while such a problem exists and no packet has yet reached the game
connection. The first game packet clears it.

### 7.4 Finding Questlog's processes

Chromium renames its processes (`CrBrowserMain`, `CrGpuMain`, …), so
`pgrep -x Questlog.exe` finds nothing. `program_name` in `questlog_start.py`
reads the Windows path from `argv[0]`, and `game_processes` keeps only
processes whose environment points at the game's prefix. Never use
`wineserver -k` in the prefix: it ends the game too.

### 7.5 Questlog's installer under Wine

The NSIS installer checks through PowerShell whether Questlog runs. Wine's
PowerShell is a stub that answers "running", so the installer tries to close
Questlog and gives up with code 2. Questlog is therefore installed by
unpacking its files (`docs/MANUAL.md`, "Installing Questlog"), and updated
by `questlog_update.py` (§6.6). Its own updater downloads new versions fine
but would start that same installer, so it is switched off.

## 8. Decisions and rejected alternatives

**Live capture through a wpcap.dll stand-in, not Questlog's replay input.**
Questlog has a hidden replay input (`QUESTLOG_REPLAY`): a file of TCP-stream
events. Fed live through a named pipe, it worked, but the delay grew by about
0.8 s per minute of play: 15 s after 35 minutes, 104 s after a few hours.
Before each line, the replay waits for the timestamp difference counted from
when it finished the previous line, so processing time is never made up.
That cannot be corrected from outside without falsifying the timestamps that
DPS and fight durations depend on. The tools from that path remain in
`tools/` (`replay_stream.py`, `pcap2questlog.py`).

**`dumpcap` on the Linux side, not Wine's builtin wpcap.** Capture needs
privileges a Wine process should not have. `dumpcap` gets them through the
`wireshark` group and its file capabilities, and runs as the normal user.

**The DLL built with clang against Wine's headers**, not MinGW: the build
needs only `clang`, `lld` and the installed Wine (`bridge/build.sh`).

**Our tray instead of fixing the Wine one** — §6.2. **The guard instead of a
patched Proton** — §6.1. **Session end after a delay instead of an immediate
one** — §6.4.

## 9. Tests and diagnostics

| What | How |
|---|---|
| launcher, bridge, quit logic, updates | `python3 -m unittest` in the repository root; the update tests build a fake installer with `7z` and run feed → download (`file://`) → checks → swap → rollback offline |
| DLL against a live bridge | `bridge/tests/bridge_client_test.exe` in a throwaway prefix, with a running `BridgeServer` and `WINEDLLOVERRIDES=wpcap=n`; report in `C:\bridge_client_test.txt` (packets, delay) |
| window-order guard | copy `bridge/tests/zorder_guard_test.exe` and `bridge/wpcap.dll` to an empty folder, then `WINEPREFIX=<throwaway> xvfb-run -a wine zorder_guard_test.exe 'Z:\<folder>\wpcap.dll'`; prints the order before and after, `PASS`/`FAIL` |
| `questlog_ctl.exe` by hand | `protontricks-launch --appid 3393110 bridge/questlog_ctl.exe hide-tray` (or `show-tray`, `close-window`, `end-session`) |
| `questlog_ctl.exe` without the game prefix | Questlog in a throwaway prefix: `wine Questlog.exe --no-sandbox --disable-gpu` under `xvfb-run`, then the commands through `wine` |
| who owns the game connection | `tools/tcp_owner_probe.exe` in the prefix |
| Wine's view of windows and focus | run the launcher with `WINEDEBUG=+event,+x11drv,+win`; the log grows about 40 KB/s, so only briefly |

Logs: the launcher's messages in its Konsole window; Questlog's and Wine's
output, including the guard's lines, in `proton-stream/questlog.log`,
rewritten on each launcher start; Steam verb switches in
`proton-stream/steam_launch.log`.

The test programs use `xvfb-run` so that they take no focus on the desktop.
Throwaway prefixes keep the game's prefix free of anything but A2Qlinux's
own files.

## 10. What Questlog updates can break

A2Qlinux depends on these properties of Questlog. `compatibility_problems`
in `questlog_update.py` checks all of them before an automatic update
(§6.6); for a manual update, check them by hand (`docs/MANUAL.md`, "Updating
Questlog"):

| Property | Used by | How to check |
|---|---|---|
| the eleven pcap calls in §4.1 | `bridge/wpcap_bridge.c` | `grep -ohE 'pcap_[a-z_]+\(' …/workers/aion-2/*.cjs \| sort -u` in the unpacked `app.asar` |
| Electron 44.5.1 (`KNOWN_ELECTRON`): tray icon id 3, `WM_ENDSESSION` ending the process | `questlog_ctl.exe` | `grep -aoE 'Electron/[0-9.]+' Questlog.exe`; for another version read `notify_icon_host.cc` and `native_window_views_win.cc` |
| `second-instance` shows the window | §6.3 | `grep -oE 'on\("second-instance",[^)]*\)' main.cjs` |
| overlay windows non-activatable (`focusable: false`) | §6.1 | `grep -c 'focusable:!1' main.cjs` |
| `resources/icon.png` in `app.asar` | `install.py` | rerun `install.py` |

## 11. Open questions

1. Does "Quit Questlog" while the game runs leave the game unaffected? It
   should: `end-session` reaches only Questlog's window. Not yet observed with
   the game.
2. Does Questlog keep its upload queue to questlog.gg (every 60 s) only in
   memory? If so, the 12 s before the session end do not drain it.
3. Questlog's desktop notifications for alerts do not work under Wine:
   `Windows.UI.Notifications.ToastNotificationManager` is missing, and
   Questlog logs `[alerts] Notifications are not supported, skipped <name>`.
   The in-game alert overlay works. The launcher could show these through
   the Linux desktop instead; not investigated.
4. The fallback of §5.2 has not been run with the game since its process
   match was corrected.
5. Questlog's keyboard shortcuts while the game has focus have not been
   tested.
