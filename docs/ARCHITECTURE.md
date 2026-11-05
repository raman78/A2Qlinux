# A2Qlinux — architecture

How A2Qlinux runs Questlog Desktop (a closed-source, Windows-only Electron
combat meter for AION 2) under Proton on Linux: what each part does, in what
order, and why it is shaped that way. Daily use is in the user guides (`docs/README.md`); this
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
runs its normal live-capture code path inside the game's Proton prefix. Its
program files stay as shipped; the one change to its folder is the removed
configuration of its own updater, `resources/app-update.yml` (§6.6).

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
- **launcher** — `a2qlinux/launcher.py`, which runs for as long as Questlog runs.
- **bridge** — the TCP link from the launcher (`BridgeServer` in
  `a2qlinux/pcap_bridge.py`) to our `wpcap.dll` inside Questlog.

## 2. Context

```
 Linux, normal user                           Proton prefix 3393110
 +-------------------------------------+     +-------------------------------+
 | a2qlinux.launcher                   |     | AION2.exe                     |
 |  +- dumpcap (TCP port 13328)        |     |                               |
 |  |   +- BridgeServer 127.0.0.1:port +---->| Questlog.exe --no-sandbox     |
 |  |      (pcap_bridge, token)        | TCP |  +- wpcap.dll (ours, in       |
 |  +- Tray -> a2qlinux.tray (desktop) |     |  |   System32\Npcap)          |
 |  +- protontricks-launch ------------+---->|  |   pcap_next_ex every 25 ms |
 |  +- protontricks-launch ------------+---->|  +- window-order guard thread |
 |       questlog_ctl.exe <command>    |     | questlog_ctl.exe (short-lived)|
 +-------------------------------------+     +-------------------------------+
        ^ SIGUSR1 / SIGUSR2
        |
 a2qlinux.desktop  <- `a2qlinux` (menu entry, desktop icon), a2qlinux-steam
```

All of A2Qlinux is one Python package, `a2qlinux`, installed with pipx
(§12). Its commands are console scripts declared in `pyproject.toml`:
`a2qlinux` (`a2qlinux.desktop:main`), `a2qlinux-run`
(`a2qlinux.launcher:run`, the launcher in the current terminal),
`a2qlinux-setup` (`a2qlinux.setup_desktop:main`) and `a2qlinux-steam`
(`a2qlinux.steam:main`).

| Module or file | Runs where | Role |
|---|---|---|
| `a2qlinux/launcher.py` | Linux | launcher: capture, bridge, starting and quitting Questlog, tray |
| `a2qlinux/pcap_bridge.py` | Linux, in the launcher | `BridgeServer`: hands captured packets to every connected DLL |
| `a2qlinux/desktop.py` | Linux | entry point of the menu entry and of `a2qlinux-steam`; opens the launcher in a terminal; one launcher at a time |
| `a2qlinux/tray.py` | Linux, child of the launcher; `--check` from `a2qlinux-setup` | our tray icon (PyQt6, drawn by the desktop's system tray) |
| `a2qlinux/steam.py` (`a2qlinux-steam`) | Linux, as Steam's launch option | starts the launcher with the game; lets the game join a running Questlog |
| `a2qlinux/config.py` | Linux, in every command | user settings from `~/.config/a2qlinux/config.toml` (§13) |
| `a2qlinux/update.py` | Linux, in the launcher; `install_fresh` from `a2qlinux-setup` | stages new Questlog versions in the background, installs them at the next start; installs Questlog the first time (§6.6) |
| `a2qlinux/setup_desktop.py` (`a2qlinux-setup`) | Linux, by hand; `refresh_entries` on every `a2qlinux` start | dependency, capture and tray checks with the commands that fix them (§14); first Questlog installation (§6.6); menu entry, icon; keeps the menu entry (and an existing desktop shortcut) running this installation's `a2qlinux` |
| `a2qlinux/bin/wpcap.dll` (from `bridge/wpcap_bridge.c`) | prefix, in Questlog's NodeService process | libpcap stand-in; window-order guard |
| `a2qlinux/bin/questlog_ctl.exe` (from `bridge/questlog_ctl.c`) | prefix, started per command | hides/shows Questlog's tray icon, closes its window, ends its session |

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
  game has been gone for `GAME_EXIT_GRACE` seconds (see §6.4). After the game,
  the game's own `steam.exe` is ended (§6.7), as Steam's Stop would; only once
  `AION2.exe` is gone and only the `steam.exe` below Steam's reaper for the
  game.
- **I3 — nothing dropped silently.** Each failure of the bridge, the guard,
  `questlog_ctl.exe` or the tray is reported: to Questlog's interface (DLL
  errors through `pcap_geterr`), to the launcher's terminal, or to
  `proton-stream/questlog.log`.
- **I4 — no traffic on disk.** The capture flows through memory only. The
  bridge token keeps other local programs from reading it (the traffic
  includes chat).

## 4. Data flow: capture

1. `a2qlinux/launcher.py` takes the lock (I1), checks that `dumpcap` is the
   distribution's root-owned binary (`system_dumpcap`), and chooses the
   network interface: the only one besides `lo` with an IPv4 address, or
   `--interface`.
2. It starts `BridgeServer` on `127.0.0.1` with a random port and token, and
   `dumpcap -F pcap` filtered to `tcp and host <address> and port 13328`.
   A thread (`pump_records`) passes each record to `BridgeServer.publish`.
3. It finds the prefix (`game_prefix`): from a running `AION2.exe`'s
   environment, else from the `libraryfolders.vdf` of each native Steam
   installation (`steam_roots`, §14). Then it installs
   `a2qlinux/bin/wpcap.dll` as `drive_c/windows/system32/Npcap/wpcap.dll`
   (`install_bridge_dll`). It replaces only an empty marker or an older build
   of ours, recognised by the string `questlog-proton bridge`
   (`BRIDGE_SIGNATURE`, kept from the project's first name: a new string
   would make an installed build look foreign). Any other file there, such as a real Npcap, is left
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
   Only the session's first connection is announced in the status window
   (`Questlog connected to the capture bridge.`); the reconnects that every
   zone change brings are normal and pass silently, while a refused or
   dropped connection is always logged.

### 4.1 The DLL's calls

| Call | Behaviour |
|---|---|
| `pcap_findalldevs` | one device carrying the address from `QUESTLOG_PROTON_BRIDGE`; without that variable, the error "No capture bridge: start Questlog with A2Qlinux", which Questlog shows |
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

Load over 30 s with the game running (8-core desktop CPU, 8 GB GPU): Questlog's
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

`a2qlinux-steam`, set as the game's Steam launch option, handles this by
always starting Questlog first and letting the game join it:

1. It starts `a2qlinux.desktop --for-game` (with any launcher options
   given before `%command%`: `--close-with-game`, `--no-auto-update`,
   which override the settings file, §13) through
   `systemd-run --user`. Started that way, the launcher and its terminal get
   the desktop session's environment instead of Steam's (overlay
   `LD_PRELOAD`, container variables), and Steam does not count them as part
   of the game. If this fails, the game still starts, with a notification.
   `--for-game` only tells `a2qlinux.desktop` who is asking (§6.5): a
   running launcher gets `SIGUSR2`, a new one starts Questlog at once.
2. It waits until Questlog runs in the prefix (`wait_for_questlog`, at most
   `QUESTLOG_UP_WAIT`, 60 s). Questlog's launch has then brought up the
   prefix's Wine session.
3. It replaces only Proton's own verb `waitforexitandrun` with `run`. `run`
   sets up drive letters for the game and Steam folders and starts the game
   without waiting, so the game joins Questlog's session. The runtime
   container keeps `--verb=waitforexitandrun`, which marks it as the game's
   main container. Each switch, and a Questlog that did not come up in time
   (the game then starts unchanged, and §5.2 takes over), is logged to
   `proton-stream/steam_launch.log`.

Why Questlog first: whichever launch starts the session's `wineserver` keeps
it, together with the session's services (`explorer.exe`, `services.exe`, …),
among its descendants. Started by Questlog's launch, the session stays out of
the game's launch, and after the game Steam can be released without touching
Questlog (§6.7). The game starts a few seconds later than without Questlog,
the time Questlog's Wine session takes to come up. Waiting for it also keeps
the two from bringing up the prefix's Wine at the same moment, which could
make two separate sessions.

Checked with the game (17 October 2026): Questlog opened without the game,
then Play. The game started at once, with one `wineserver` shared by both.
Checked with the game from Play alone (20 October 2026): Questlog came up in
a second, the game joined its session, and after the game Steam was released
by ending `steam.exe` (§6.7) while Questlog and its `wineserver` ran on, not
restarted.

### 5.2 Fallback without the launch option

When Play is pressed without `a2qlinux-steam`, the launcher sees a pending
launch (`steam_launch_pending`). It looks for Proton's own process,
`python3 …/proton waitforexitandrun …AION2.exe`, with the game's app id in
its environment, while no `AION2.exe` runs yet. It then closes Questlog
(`close_questlog`), waits for the game (`wait_for_game_or_cancel`) and starts
Questlog again on the same bridge. If Steam gives up (10 s with no pending
launch), Questlog comes back without the game.

Only Proton's process counts, in exactly that shape. An earlier version
matched any process whose command line contained `waitforexitandrun`. Steam
runs the launch option first in the chain, so `a2qlinux-steam` itself
briefly carried the original command line. That version sent `wineboot -e`
into the session where the game was starting, which closed Questlog and
aborted the game.

An earlier version started the launcher with `--wait-for-game`, which
started Questlog only once `AION2.exe` had run for 2 s. The game's launch
then owned the Wine session, and after every game Questlog had to be
restarted to release Steam (§6.7).

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
  `[a2qlinux] Questlog window … moved it below.` A failed move is
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
(`a2qlinux/tray.py`, `QSystemTrayIcon`, which KDE serves as a
StatusNotifierItem; Qt falls back to an XEmbed tray icon on X11 desktops
without a StatusNotifierItem host). Its menu is drawn by the desktop, outside
Wine's foreground rules. The tray process only prints `open` or `quit` on stdout; class `Tray`
in `a2qlinux/launcher.py` reads that into `Requests`. The tray runs in its own
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

So "Quit Questlog" in our tray (`QuitControl` in `a2qlinux/launcher.py`)
ends Questlog `SAVE_WAIT` (10.5 s) after the last game data reached it, not
after the click. The launcher knows when that was: every packet passes
through its bridge, and `pump_records` stamps the time
(`status["last_packet"]`). Without the game, or with the game closed for
10.5 s, nothing is pending and Questlog ends at once, in about 1 s. With the
game running, packets keep arriving, so the quit takes up to 10.5 s:

```
 "quit" ---> tray-off (+ close-window if the end is not immediate:
               |       Questlog hides, keeps running)
               |  until SAVE_WAIT after the last game data (0 if long ago)
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
- An "open" (`SIGUSR1`, tray) or "keep" (`SIGUSR2`, Steam) during the wait
  calls the quit off: the tray comes back, and for "open" the window is
  shown. Once `end-session` has been sent, such a request makes the launcher
  start Questlog again on the same bridge after it has gone.

`after_game = "close"` (§13) or `--close-with-game` uses `close_questlog`
instead: `wineboot -e` `GAME_EXIT_GRACE` seconds (setting `after_game_delay`,
15 by default) after `AION2.exe` has gone, by which time nothing is left
but Questlog. It was written before `questlog_ctl.exe` existed and is kept for
that case. `wineboot -e` must never be sent while the game runs or is
starting (§5.2).

After either way of ending Questlog with the game gone,
`release_steam_after_questlog` waits up to `SESSION_END_WAIT` for the Wine
session to close and ends any `steam.exe` of the game left over (§6.7, step
3b). Without that, a quit in the two seconds before the launcher releases
Steam after the game would leave Steam showing AION 2 as running. While the
game runs, or with no `steam.exe` of the game left, it does nothing and does
not wait.

Electron's auto-update would install on quit (`autoInstallOnAppQuit`); it is
switched off (§6.6), and the session end would skip it anyway.

### 6.5 Signals between the menu entry and the launcher

`a2qlinux/desktop.py` is what the menu entry, the desktop icon and
`a2qlinux-steam` run. If no launcher holds the lock, it opens
`a2qlinux/launcher.py` in a terminal window, the status window
(`terminal_command`, §14). Otherwise it signals the PID read from the lock file
(`launcher_pid`), after checking that the process's command line contains
`a2qlinux.launcher`, so a stale or reused PID is never signalled:

| Caller | Signal | Launcher's response |
|---|---|---|
| menu entry, desktop icon | `SIGUSR1` | show Questlog's window; call off a pending quit |
| `a2qlinux-steam` (`--for-game`) | `SIGUSR2` | keep Questlog running; call off a pending quit; no window |

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
never installed. `a2qlinux/update.py` does the update instead, the same way as
a manual update, which therefore remains the fallback (`docs/UPDATING.md`,
"Updating by hand"). The first installation uses the same code (end of this
section).

```
 at every launch:  disable_builtin_updater -> install_staged -> Questlog
                                                     ^
                                                     | a staged version
 in the background (60 s after start, then every     | that fits
 6 h; deferred while AION2.exe runs):                |
   stage(): feed -> download -> size + SHA-512 -> 7z -> checks
            -> <state>/update/<version>/app
            -> <state>/update/staged.json  (verdict: fits / why not)
```

1. **`disable_builtin_updater`** removes `resources/app-update.yml`, the only
   configuration electron-updater runs on. Questlog then logs
   `[updater] … ENOENT … app-update.yml` every 5 minutes and does nothing
   else: it downloads nothing and never shows its "update ready" prompt,
   which appears only after a download. Tested in a throwaway prefix.
2. **`stage`**, in a thread (`check_for_updates` in `a2qlinux/launcher.py`): first
   check 60 s after the start, then every `UPDATE_CHECK_EVERY` (setting
   `update_check_hours`, 6 by default). While
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
`auto_update = false` (§13) or `--no-auto-update` turns off steps 2–4. Step 1 stays, since the built-in
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

**First installation** (`install_fresh`, run by `a2qlinux-setup` when the
Questlog folder has no `Questlog.exe`). It reads the feed (`read_feed`) and
runs the same download, size and SHA-512 check, unpacking and
`compatibility_problems` as `stage` (both through `_fetch`), then renames
the unpacked program into place. Differences from an update, and why:

- No staging and no "next start": nothing runs yet, so the program goes
  straight into place.
- The work folder is a temporary folder next to the target
  (`.a2qlinux-questlog-*` in its parent), so the final move is a rename on
  one file system, and it is deleted whatever happens, including Ctrl+C.
- It never writes into a folder that exists and holds anything: a folder
  without `Questlog.exe` but with other files is reported, not filled.
- A version that does not fit is not installed. Unlike an update, there is
  no older version to keep, so the message names the two ways out:
  a newer A2Qlinux, or an earlier Questlog by hand.
- Errors are raised as `RuntimeError` with the reason and what to do;
  `a2qlinux-setup` lists them under "Not ready yet".

Checked against the real CDN (4 November 2026) with an empty home folder:
Questlog 0.1.48 downloaded, verified, unpacked, judged to fit and put in
place by `a2qlinux-setup`, followed by "Ready".

### 6.7 Releasing Steam after the game

**Symptom.** After the game is closed, Steam keeps showing AION 2 as running
(and counting play time, with Stop instead of Play) for as long as Questlog
runs.

**Cause** (Proton's `steam_helper/steam.c` and `proton` script, Wine's
`server/process.c`, pressure-vessel's `pv-adverb`). Steam counts the game as
running until its `reaper` for the game ends. Below the reaper are the
runtime container, whose `pv-adverb` is a subreaper that by default waits for
every descendant (`--no-terminate-with-main`), Proton's script, and the
`steam.exe` that starts the game. `steam.exe` marks itself a Wine *system*
process (`ProcessWineMakeProcessSystem`) and waits on the event that request
returns, which the server signals when no *user* process is left in the
session. Questlog is a user process in the game's session (§1), so
`steam.exe`, and everything above it, waits for Questlog.

**Rejected: marking Questlog as a system process.** The server would accept
it (`make_process_system` takes any process handle), but when the last user
process ends it signals system processes to exit and kills them two seconds
later (`server_shutdown_timeout`). Questlog would die about 5 s after the
game, and at once when started without it. A Wine process cannot move to
another session either; it is bound to its wineserver for life.

**What decides the remedy** is which launch started the session's
`wineserver`. It stays a descendant of that launch's container for life,
with the session's services (`explorer.exe`, `services.exe`, `winedevice.exe`,
…):

| Session started by | Left of the game's launch once `AION2.exe` is gone | Remedy |
|---|---|---|
| Questlog's launch (the normal case, §5.1) | Proton's script and `steam.exe` | end `steam.exe`; Questlog stays as it is |
| the game's launch (Play without the launch option, §5.2; or Questlog not up in time) | also the `wineserver` and the session's services | Questlog has to leave the session: restart it |

**What the launcher does**, unless `after_game = "close"` (or
`--close-with-game`) or a quit is in progress. Every 0.5 s once `AION2.exe`
is gone, `game_launch_state` reads the process table (`process_table`),
walks up from the game's `steam.exe` to Steam's `reaper`, and looks at
everything below it. `AfterGame` turns the answer into an action:

- **`release`** — below the reaper, no `wineserver` and no Windows program
  besides `steam.exe`. Once that has held for `RELEASE_SETTLE` (2 s; a game
  that restarts itself goes through `steam.exe`),
  `end_game_steam_helper` sends `steam.exe` SIGTERM. Proton's script, the
  container and the reaper end with it within a second, and Steam shows Play.
  Questlog is not touched and loses nothing. Checked with the game
  (20 October 2026): 2 s after `AION2.exe` exited only the script and
  `steam.exe` were left; 0.5 s after the SIGTERM the reaper was gone, while
  Questlog's eight processes and its session ran on.
- **`wait`** — other Windows programs of the game's launch still run (the
  game's `EpicWebHelper.exe`, say). Nothing is done; `steam.exe` would wait
  for them too. If it lasts, the launcher names them.
- **`restart`** — a `wineserver` is below the reaper, or `steam.exe` has no
  reaper above it and the launch cannot be told. The restart comes
  `SAVE_WAIT` (10.5 s) after the last game data reached Questlog
  (`status["last_packet"]`, as for the quit in §6.4), since ending the session
  skips Questlog's own save; with the game closed that is about 10.5 s after
  it closed.
  1. `find_questlog_window` records whether Questlog's main window is shown.
  2. `move_to_fresh_session`: `questlog_ctl.exe end-session`, then
     `wait_for_questlog_exit`.
  3. It waits up to `SESSION_END_WAIT` (30 s) until `wine_session_running`
     finds no `wineserver` for the prefix (by `WINEPREFIX`, else
     `STEAM_COMPAT_DATA_PATH/pfx`). If another program keeps the session
     open (a second meter, say), this is logged, since Steam then stays
     "running" because of that program, and step 4 follows without step 3b.
  3b. `end_game_steam_helper` (through `release_steam_after_questlog`, also
     used after a quit, §6.4): any `steam.exe` with the game's app id still
     alive at this point gets SIGTERM. Observed with the real game: the
     session's wineserver had exited, yet `steam.exe` slept on in the kernel
     (all three threads in `ntsync_schedule`: Proton's ntsync waits do not
     go through the server, so the server's exit does not wake them), and
     Steam showed the game running for hours.
  4. `start_questlog(hidden=not shown)` starts Questlog again on the same
     bridge, with Questlog's own `--hidden` switch if its window was not
     shown. It runs in a session of its own, so the next game joins that one
     and ends with `release`.
- **`free`** — no `steam.exe` of the game is left (Stop was pressed in Steam,
  say). Nothing to do.

The restart path was checked with a stand-in game and, up to step 3b, with
the real game (18 October 2026); step 3b by hand on the orphaned `steam.exe`.

**Edge.** If Play is pressed in the few seconds while an old session shuts
down during a restart, the game may join a session that is closing. Not
observed; the window is a few seconds, and only after a game that started
the session itself.

## 7. Failure modes

| Symptom | Cause | Where to look |
|---|---|---|
| Questlog quits at once, "GPU process isn't usable" | Chromium's sandbox inside Steam's container (§7.1) | `questlog.log` |
| Questlog shows "No capture bridge: start Questlog with A2Qlinux" | Questlog started without the launcher | start it from the menu entry |
| "Capture bridge not reachable (is A2Qlinux running?)" | launcher not running (terminal closed) | status window |
| "Capture bridge closed the connection …" | launcher stopped, or it dropped a connection | status window |
| Steam "launching" forever while Questlog runs | Proton waiting for an idle prefix (§5.1) | `steam_launch.log`; set the launch option |
| click in the game activates Questlog | §6.1; guard not running | `questlog.log`, `[a2qlinux]` lines |
| two Questlog tray icons | `hide-tray` failed | status window, `Questlog control:` lines |
| "Aion 2's traffic can't be read" before logging in | §7.3, harmless | — |
| "A2Qlinux is already running in another window" | second launcher refused (I1) | use the running one |
| "Questlog is already running in the game prefix without the capture bridge" | Questlog started outside A2Qlinux | quit it from its own tray icon |
| Tracker Map overlay blank after restarting Questlog mid-game | Questlog learns the character's zone only at login or zone change | change zone |
| "Questlog update check failed (…)" | no network, CDN change | none; retried at the next check |
| "Questlog X does not fit this A2Qlinux yet …" (notification) | a check of §10 failed | A2Qlinux needs a change for that version; the installed one stays |
| "Questlog X ended within 60 s … going back" | the new version did not start under Proton | the previous version runs again; the failed one is in `<folder>-X-failed` |
| notification "No terminal for the status window was found" | none of `TERMINALS` installed (§14) | install one |
| "AION 2's Wine prefix was not found …" / "Only a Flatpak Steam was found" | no prefix in any native installation's libraries; only a Flatpak Steam (§14) | the message lists the files read |
| `a2qlinux-setup`: "A2Qlinux's tray icon cannot run here (…)" | no system tray, or Qt cannot start (§14) | the `qt.qpa` lines in the message |
| `a2qlinux-setup`: "capturing is not allowed yet (…)" | the capture check failed (§14) | `dumpcap`'s own line in the message, and the commands listed |
| `a2qlinux-setup`: "Questlog X does not fit …" / "could not be installed" / "not an empty folder" | `install_fresh` refused or failed (§6.6) | the reason in the message |

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
`pgrep -x Questlog.exe` finds nothing. `program_name` in `a2qlinux/launcher.py`
reads the Windows path from `argv[0]`, and `game_processes` keeps only
processes whose environment points at the game's prefix. Never use
`wineserver -k` in the prefix: it ends the game too.

### 7.5 Questlog's installer under Wine

The NSIS installer checks through PowerShell whether Questlog runs. Wine's
PowerShell is a stub that answers "running", so the installer tries to close
Questlog and gives up with code 2. Questlog is therefore installed by
unpacking its files: by `a2qlinux-setup` (`install_fresh`, §6.6) or by hand
(`docs/UPDATING.md`, "Installing Questlog by hand"), and updated by
`a2qlinux/update.py` (§6.6). Its own updater downloads new versions fine
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
needs only `clang`, `lld` and the installed Wine's development files
(`bridge/build.sh`, §14). The result is not tied to that Wine: the two
parts import only documented Win32 functions by name (`kernel32`, `user32`,
`ws2_32`, `ucrtbase`, `shell32`; `llvm-objdump -p`), so a Wine update needs
no rebuild. Observed: the build here against system Wine 11.21 runs daily
under Proton's Wine 11.0, and the PyPI package's parts are built against
whatever Wine the CI container has.

**Our tray instead of fixing the Wine one** — §6.2. **The guard instead of a
patched Proton** — §6.1. **Session end after a delay instead of an immediate
one** — §6.4.

## 9. Tests and diagnostics

| What | How |
|---|---|
| launcher, bridge, quit logic, updates, Steam verb switch | `python3 -m unittest` in the repository root (no built Windows parts needed; CI runs `bash bridge/build.sh` and the tests on every push, §12); the update tests build a fake installer with `7z` and run feed → download (`file://`) → checks → swap → rollback, and the first installation (`install_fresh`), offline |
| DLL against a live bridge | `bridge/tests/bridge_client_test.exe` in a throwaway prefix, with a running `BridgeServer` and `WINEDLLOVERRIDES=wpcap=n`; report in `C:\bridge_client_test.txt` (packets, delay) |
| window-order guard | copy `bridge/tests/zorder_guard_test.exe` and `a2qlinux/bin/wpcap.dll` to an empty folder, then `WINEPREFIX=<throwaway> xvfb-run -a wine zorder_guard_test.exe 'Z:\<folder>\wpcap.dll'`; prints the order before and after, `PASS`/`FAIL` |
| `questlog_ctl.exe` by hand | `protontricks-launch --appid 3393110 <package>/a2qlinux/bin/questlog_ctl.exe hide-tray` (or `show-tray`, `close-window`, `end-session`); `<package>` is printed by `python -c 'import a2qlinux; print(a2qlinux.__path__[0])'` in A2Qlinux's environment |
| `questlog_ctl.exe` without the game prefix | Questlog in a throwaway prefix: `wine Questlog.exe --no-sandbox --disable-gpu` under `xvfb-run`, then the commands through `wine` |
| who owns the game connection | `tools/tcp_owner_probe.exe` in the prefix |
| Wine's view of windows and focus | run `WINEDEBUG=+event,+x11drv,+win a2qlinux-run`; the log grows about 40 KB/s, so only briefly |

Logs: the launcher's messages in its status window (the terminal); Questlog's and Wine's
output, including the guard's lines, in `proton-stream/questlog.log`,
rewritten on each launcher start; Steam verb switches in
`proton-stream/steam_launch.log`.

The test programs use `xvfb-run` so that they take no focus on the desktop.
Throwaway prefixes keep the game's prefix free of anything but A2Qlinux's
own files.

## 10. What Questlog updates can break

A2Qlinux depends on these properties of Questlog. `compatibility_problems`
in `a2qlinux/update.py` checks all of them before an automatic update
(§6.6); for a manual update, check them by hand (`docs/UPDATING.md`,
"Updating by hand"):

| Property | Used by | How to check |
|---|---|---|
| the eleven pcap calls in §4.1 | `bridge/wpcap_bridge.c` | `grep -ohE 'pcap_[a-z_]+\(' …/workers/aion-2/*.cjs \| sort -u` in the unpacked `app.asar` |
| Electron 44.5.1 (`KNOWN_ELECTRON`): tray icon id 3, `WM_ENDSESSION` ending the process | `questlog_ctl.exe` | `grep -aoE 'Electron/[0-9.]+' Questlog.exe`; for another version read `notify_icon_host.cc` and `native_window_views_win.cc` |
| `second-instance` shows the window | §6.3 | `grep -oE 'on\("second-instance",[^)]*\)' main.cjs` |
| overlay windows non-activatable (`focusable: false`) | §6.1 | `grep -c 'focusable:!1' main.cjs` |
| `resources/icon.png` in `app.asar` | `a2qlinux-setup` | rerun `a2qlinux-setup` |

## 11. Open questions

1. Does "Quit Questlog" while the game runs leave the game unaffected? It
   should: `end-session` reaches only Questlog's window. Not yet observed with
   the game.
2. Does Questlog keep its upload queue to questlog.gg (every 60 s) only in
   memory? If so, the wait before the session end does not drain it.
3. Questlog's desktop notifications for alerts do not work under Wine:
   `Windows.UI.Notifications.ToastNotificationManager` is missing, and
   Questlog logs `[alerts] Notifications are not supported, skipped <name>`.
   The in-game alert overlay works. The launcher could show these through
   the Linux desktop instead; not investigated.
4. The fallback of §5.2 has not been run with the game since its process
   match was corrected.
5. Questlog's keyboard shortcuts while the game has focus have not been
   tested.

## 12. Packaging and releases

A2Qlinux ships as the Python package `a2qlinux`, installed with pipx. The
layout follows the author's `sto-warp` project, so both are released the same
way. The step-by-step release procedure is `docs/RELEASE.md`; this section
records how the pieces fit and why.

**Package.** `pyproject.toml` (hatchling) declares the four commands of §2 and
the two dependencies that are not part of a desktop system: PyQt6 (tray) and
python-xlib (finding Questlog's window). The version comes from the git tag
through hatch-vcs (`v0.1.0` → 0.1.0; between tags `0.1.devN`), written to
`a2qlinux/_version.py` at build time and read by `a2qlinux.__version__`.

**Windows parts.** `wpcap.dll` and `questlog_ctl.exe` are built by
`bridge/build.sh` into `a2qlinux/bin/` and shipped inside the package, so a
user needs neither clang nor Wine's headers. They are ignored by git, so
`pyproject.toml` lists them as hatchling `artifacts`, for both the sdist and
the wheel. Both matter: `python -m build` builds the wheel *from* the sdist,
and an sdist without the binaries gave a wheel without them, which installed
cleanly and failed only when the launcher looked for the DLL. The test
programs and `tools/` probes stay out of the packages.

**CI** (`.github/workflows/`), both in an `archlinux:latest` container so that
the toolchain is the one `bridge/build.sh` is used with (Wine is in Arch's
`extra`):

| Workflow | When | What |
|---|---|---|
| `tests.yml` | every push to `develop` or `main`, pull requests | `bridge/build.sh`, `python -m unittest` |
| `release.yml` | a published GitHub Release; or by hand | build, tests, sdist + wheel, check that the wheel holds both Windows parts and that its version equals the tag, attach both packages to the release (by hand: keep them as a workflow artifact) |

In the container, `git` is installed before `actions/checkout`, which
otherwise downloads a tarball without history, leaving hatch-vcs no tag to
read. The checkout is marked `safe.directory`, because it belongs to another
user there.

**PyPI.** Users install with `pipx install a2qlinux` and update with
`pipx upgrade a2qlinux`. The `pypi` job in `release.yml` runs after `build`,
on published releases only, and uploads the two files `build` attached to the
release, downloaded back with `gh release download`. It does not build again:
the Windows parts exist only in the Arch container, and uploading the checked
files means PyPI and the GitHub Release carry identical packages. It
authenticates through a Trusted Publisher on pypi.org (project `a2qlinux`,
repository `raman78/A2Qlinux`, workflow `release.yml`, no environment), so no
token is stored in the repository. `skip-existing` makes a re-run after a
partial upload succeed instead of failing on the file already there. sto-warp
publishes from a single job that builds on the runner; A2Qlinux differs only
because of the Windows parts.

`README.md` is the package's description on PyPI, where relative links do not
resolve, so its links to `docs/` and `LICENSE` are absolute URLs on `main`,
i.e. the documentation of the latest release.

**Branches.** Work happens on `develop`; a release fast-forwards `main` to it
and tags `main` (`docs/RELEASE.md`). `main` therefore always equals the last
release.

## 13. Settings

`a2qlinux/config.py` reads `~/.config/a2qlinux/config.toml` (or under
`$XDG_CONFIG_HOME`) with the standard library's `tomllib`. `a2qlinux-setup`
writes it when missing (`config.template`), with every setting at its
default and a comment for each. It changes an existing file in one case
only: `a2qlinux-setup --questlog-dir` (`config.set_questlog_dir`) replaces
the `questlog_dir` line, or adds it, and leaves every other line and comment
as it was. The setup then reads the folder back from the file, like every
other command, so the folder it checks and installs Questlog into is the
one the launcher uses later. An earlier version only wrote the option into
a new file; with a file already there, the option was refused, and the
first-installation code would have installed into a folder the settings did
not name.

| Setting | Default | Replaces | Read by |
|---|---|---|---|
| `questlog_dir` | `~/Games/Questlog` | the `QUESTLOG_DIR` default | launcher (`--exe`), `a2qlinux.desktop` (lock file), `a2qlinux-steam`, `a2qlinux-setup` |
| `interface` | `""` (automatic) | — | launcher (`--interface`) |
| `after_game` | `"keep"` | — | launcher: §6.7 (`"keep"`) or `close_questlog` (`"close"`) |
| `after_game_delay` | `15`, at least 10.5 | `GAME_EXIT_GRACE` | launcher, with `after_game = "close"` only |
| `auto_update` | `true` | — | launcher, §6.6 |
| `update_check_hours` | `6`, at least 0.25 | `UPDATE_CHECK_EVERY` | launcher, §6.6 |

**Precedence**, highest first: a command-line option (`--exe`,
`--interface`, `--close-with-game`, `--no-auto-update`), the environment
(`QUESTLOG_DIR`), the file, the default. Options stay because they are what
the Steam launch option and a one-off start can pass.

**What is deliberately not a setting.** Values that follow from how Questlog,
Electron or Wine behave, not from preference: `SAVE_WAIT` (Questlog saves
within 10 s; a smaller value loses data), `SESSION_END_WAIT`,
`STEAM_HELPER_WAIT`, `RELEASE_SETTLE`, `QUESTLOG_UP_WAIT`, `QUESTLOG_QUIT_WAIT`, `HANDOVER_WAIT`,
`CLIENT_QUEUE_RECORDS`, `GUARD_INTERVAL_MS`. They are named constants next to
the code they govern and are described in the sections above.

**Errors** never stop A2Qlinux and are never dropped: `config.load` returns
each one with the file and line (an unknown name, a value of the wrong type,
a value outside its choices or below its minimum, a file that is not valid
TOML), and the setting concerned keeps its default. The launcher logs each
problem (`Settings: …`) and sends one desktop notification. A `true`/`false`
where a number is expected is refused rather than read as 1/0.

## 14. Distributions and desktops

Developed and played on the one setup named at the top of this document. What depends on the
distribution or desktop, how A2Qlinux copes with it, and how that was
established. Package names per distribution are in `docs/INSTALL.md`; they
were read from each distribution's package index (Debian, Ubuntu through
Launchpad, Fedora's mdapi, openSUSE Tumbleweed's repository) in October
2026, including which package installs `/usr/bin/7z`: Debian 12's `7zip`
has only `7zz`, so Debian and Ubuntu use `p7zip-full`, which on newer
releases is a transitional package for a `7zip` that does install `7z`.

**Status window: the terminal** (`TERMINALS`, `terminal_command` in
`a2qlinux/desktop.py`). The first one found of Konsole, GNOME Terminal,
Ptyxis, the Xfce and MATE terminals, `x-terminal-emulator` and `xterm`.
Each is given the program and its arguments as separate words, after the
option its manual names for that: `-e` (Konsole, xterm), `--` (GNOME
Terminal, Ptyxis), `-x` (Xfce, MATE). `x-terminal-emulator` is Debian's
alternative for the installed terminal; Debian policy requires it to take
`-e` with separate words, which covers terminals not listed. GNOME Console
(`kgx`) is not listed by name: it takes everything after `-e` as the
command only from version 47 (`kgx_filter_arguments` in its source; absent
in 46.0). Debian 13 ships 48 and registers it as `x-terminal-emulator`,
which is how it is reached there. Only Konsole has been run with
A2Qlinux. Without any of them the menu entry
does not start the launcher with no window; it says which to install
(notification and stderr), and `a2qlinux-setup` lists it as missing.

**Tray icon.** `a2qlinux-setup` runs `a2qlinux.tray --check`: the real
tray module, up to `QSystemTrayIcon.isSystemTrayAvailable()`, without
showing an icon (`tray_problem` in `a2qlinux/setup_desktop.py`). It reports
the two failures seen in testing, with the tray's own words: no system tray
(GNOME without the AppIndicator extension; reproduced under Xvfb with a
private D-Bus session), and Qt unable to load its platform plugin. The
second matters on X11 sessions: the PyQt6 wheels pip installs bundle Qt,
whose `xcb` plugin needs the system's `libxcb-cursor.so.0` (and other xcb
libraries), which pip cannot install. Reproduced by hiding that library in
a private mount namespace (`unshare -rm`, bind-mounting `/dev/null` over
it) under Xvfb: Qt aborts with "From 6.5.0, xcb-cursor0 or libxcb-cursor0
is needed to load the Qt xcb platform plugin". Qt sends its messages to the
journal when stderr is not a terminal, so the check sets
`QT_FORCE_STDERR_LOGGING=1`; without it the reason was lost and only the
exit code (-6) remained. Wayland sessions use Qt's `wayland` plugin and do
not need the xcb libraries.

**Steam's location** (`steam_roots` in `a2qlinux/launcher.py`). Valve's
launcher (`bin_steam.sh`) keeps `~/.steam/steam` pointing at the
installation, wherever it is; `~/.steam/root` and the usual folders
(`$XDG_DATA_HOME/Steam`, `~/Steam`) follow, each resolved and listed once.
Steam from Flatpak is not supported: its permissions (Flathub's
`com.valvesoftware.Steam` manifest) give it no access to the home folder,
so the launch option cannot reach `~/.local/bin/a2qlinux-steam` or the
Python environment behind it. When only a Flatpak Steam exists,
`game_prefix` says so instead of reporting a missing prefix.

**Missing packages: one command per distribution** (`missing_packages`,
`install_commands`, `distro_family` in `a2qlinux/setup_desktop.py`).
`a2qlinux-setup` reads `/etc/os-release` and maps `ID` and `ID_LIKE` to a
family: Arch, Ubuntu (checked before Debian, since Ubuntu's derivatives name
both), Debian, Fedora, SUSE. `PACKAGES` holds each family's package names,
the same as the table in `docs/INSTALL.md`; `install_commands` turns the
missing ones into one `sudo <package manager> install …` line. Two special
cases follow the package indexes: Ubuntu gets `add-apt-repository multiverse`
in front when protontricks is missing; Debian other than 12 gets
`pipx install protontricks` instead. An unknown distribution gets Arch's
names and a pointer to the guide. A missing xcb-cursor library is known only
from the tray check's message, so it joins the command from there. The
setup prints these commands and never runs `sudo` itself.

**Capture check** (`capture_problem`). `dumpcap -D` is no check: listing
devices needs no rights, and a copy of `dumpcap` without capabilities listed
them as well as the real one. The setup therefore captures for one second
on `lo` with a filter that matches nothing (`tcp port 1`), written to a
pipe that is discarded (I4 holds: no traffic is written anywhere). Measured:
the real `dumpcap` exits 0 in about one second; the copy without
capabilities exits 1 with "You do not have permission to capture on device
"lo"". On failure the message carries `dumpcap`'s own line and the steps
that apply: `dpkg-reconfigure wireshark-common` on Debian and Ubuntu when
`dumpcap` has neither file capabilities nor the setuid bit (Fedora and
openSUSE give it capabilities, as Arch does: their package files
`wireshark.spec` and `permissions.secure`); `usermod -aG wireshark` when the
group database lacks the user (`id -nG <user>`); a new login when the
running session lacks the group (`id -nG`). On Arch, Fedora and openSUSE
`dumpcap` is `root:wireshark 0750`, so a user outside the group cannot even
run it, and `shutil.which` (which tests for execute permission) does not
find it. The setup looks programs up by existence (`installed`), so this
case reads as a missing group membership, not as a missing package.

**Other requirements.** Python 3.11 for `tomllib` (§13), declared in
`requires-python`, so pipx refuses older Pythons (Ubuntu 22.04 has 3.10).
`systemd-run --user` for the Steam launch option (§5.1). A native
`protontricks-launch`; Debian 13 has no protontricks package, and
`pipx install protontricks` provides the command (its wheel's entry
points). Debian's `wireshark-common` asks whether non-root users may
capture, with no as the default (its debconf template `install-setuid`);
`dpkg-reconfigure wireshark-common` changes the answer.

**Building from source** (`bridge/build.sh`, `install-from-source.sh`).
The build needs `clang`, `ld.lld` and Wine's headers and x86_64 import
libraries. Where the distributions put the latter, from their package file
lists: headers under `/usr/include/wine` (Arch, Fedora, openSUSE) or
`/usr/include/wine/wine` (Debian, Ubuntu, package `libwine-dev`); import
libraries in `x86_64-windows` under `/usr/lib/wine` (Arch),
`/usr/lib64/wine` (openSUSE) or `/usr/lib/x86_64-linux-gnu/wine` (Debian,
Ubuntu). `build.sh` tries these in turn, takes `WINE_INCLUDE` / `WINE_LIB`
over them, and when something is missing prints the family's install line
(from `/etc/os-release`, as `a2qlinux-setup` does) and exits 1 before
compiling. Fedora 44's `wine-devel` file list (mdapi) showed only
`i386-windows` import libraries; whether its x86_64 ones live under
`/usr/lib64/wine` is not established, and the build would then say so.
Checked here: the detected Arch paths and a Debian-shaped layout given
through the variables build code and data sections identical to the
previous script's (`llvm-objdump` of `.text`, `.rdata`, `.data`; the files
differ only in the PE time stamp, which changes on every build). Only Arch
has built it for real. `install-from-source.sh` runs `build.sh`,
`pipx install --editable .` (after `pipx uninstall a2qlinux` if one is
installed, since pipx refuses a second install), `pipx ensurepath` and
`a2qlinux-setup` with `PIPX_BIN_DIR` (default `~/.local/bin`) put first on
`PATH`, so the menu entry points at pipx's stable command folder rather
than at the environment's own `bin`.
