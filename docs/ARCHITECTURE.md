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
 |  +- dumpcap per interface, TCP 13328|     |                               |
 |  |   +- BridgeServer 127.0.0.1:port +---->| Questlog.exe --no-sandbox     |
 |  |      (pcap_bridge, token)        | TCP |  +- wpcap.dll (ours, in       |
 |  +- Tray -> a2qlinux.tray (desktop) |     |  |   System32\Npcap)          |
 |  +- protontricks -c (own scope) ----+---->|  |   pcap_next_ex every 25 ms |
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
(`a2qlinux.steam:main`). `a2qlinux --version` and `a2qlinux --diagnose
[--report]` are answered by `a2qlinux.desktop:main` itself, before it would
open a status window (§12 "Shown version", §9.1).

| Module or file | Runs where | Role |
|---|---|---|
| `a2qlinux/launcher.py` | Linux | launcher: capture, bridge, starting and quitting Questlog, tray |
| `a2qlinux/pcap_bridge.py` | Linux, in the launcher | `BridgeServer`: lists the captured interfaces to the DLL and hands each interface's packets to the DLL connections that opened it |
| `a2qlinux/desktop.py` | Linux | entry point of the menu entry and of `a2qlinux-steam`; opens the launcher in a terminal; one launcher at a time |
| `a2qlinux/tray.py` | Linux, child of the launcher; `--check` from `a2qlinux-setup` | our tray icon (PyQt6, drawn by the desktop's system tray) |
| `a2qlinux/steam.py` (`a2qlinux-steam`) | Linux, as Steam's launch option | starts the launcher with the game; lets the game join a running Questlog |
| `a2qlinux/config.py` | Linux, in every command | user settings from `~/.config/a2qlinux/config.toml` (§13) |
| `a2qlinux/update.py` | Linux, in the launcher; `install_fresh` from `a2qlinux-setup` | stages new Questlog versions in the background, installs them at the next start; installs Questlog the first time (§6.6) |
| `a2qlinux/setup_desktop.py` (`a2qlinux-setup`) | Linux, by hand; `refresh_entries` on every `a2qlinux` start | dependency, capture and tray checks with the commands that fix them (§14); first Questlog installation (§6.6); menu entry, icon (§12, "Name and icon"); keeps the menu entry (and an existing desktop shortcut) running this installation's `a2qlinux`, with the current name and icon |
| `a2qlinux/diagnose.py` | Linux, `a2qlinux --diagnose [--report]` by hand | read-only diagnosis, and a problem report the user can file as a GitHub issue (§9.1) |
| `a2qlinux/bin/wpcap.dll` (from `bridge/wpcap_bridge.c`) | prefix, in Questlog's NodeService process | libpcap stand-in; window-order guard |
| `a2qlinux/bin/questlog_ctl.exe` (from `bridge/questlog_ctl.c`) | prefix, started per command | hides/shows Questlog's tray icon, closes its window, ends its session |

## 3. Invariants

- **I1 — one launcher.** `session_lock` holds an exclusive `flock` on
  `<Questlog dir>/proton-stream/.lock` for the launcher's lifetime and writes
  its PID into the file. A second launcher would start a second bridge, while
  its Questlog launch would hand over to the running Questlog on the first
  bridge. Holding the lock is also proof that no other launcher runs, so
  a Questlog found with the bridge in its environment was left by one that
  has ended (§6.11).
- **I2 — Questlog only.** Nothing A2Qlinux does acts on other programs in the
  prefix (the game, other meters such as NotMeter). Per-object Windows calls
  (one icon, one window) are used instead of prefix- or session-wide switches.
  The one exception, `wineboot -e` in `close_questlog`, runs only when the
  game has been gone for `GAME_EXIT_GRACE` seconds (see §6.4). After the game,
  the game's own `steam.exe` is ended (§6.7), as Steam's Stop would; only once
  `AION2.exe` is gone and only the `steam.exe` below Steam's reaper for the
  game. With the user's consent, `a2qlinux-setup` adds one registry entry
  to the prefix: a command for the verb "explore" of folders, which Wine
  lacks (§6.10). It only fills a gap: it is never written over a command
  that is already there, and in its absence every such call fails.
- **I3 — nothing dropped silently.** Each failure of the bridge, the guard,
  `questlog_ctl.exe` or the tray is reported: to Questlog's interface (DLL
  errors through `pcap_geterr`), to the launcher's terminal, or to
  `proton-stream/questlog.log`.
- **I4 — no traffic on disk.** The capture flows through memory only. The
  bridge token keeps other local programs from reading it (the traffic
  includes chat).

## 4. Data flow: capture

1. `a2qlinux/launcher.py` takes the lock (I1) and checks that `dumpcap` is the
   distribution's root-owned binary (`system_dumpcap`).
2. It starts `BridgeServer` on `127.0.0.1` with a random port and token.
   `Captures` then starts one `dumpcap -F pcap` per network interface with
   an IPv4 address besides `lo` (or per interface named in the `interface`
   setting or `--interface`), filtered to
   `tcp and host <that interface's address> and port 13328`, and registers
   each interface with the bridge as a channel. A thread per interface
   (`pump_records`) passes each record to `BridgeServer.publish`. Why every
   interface, and how the set follows a VPN going up and down: §4.3.
   A second thread per interface (`relay_dumpcap_messages`) reads that
   `dumpcap`'s stderr and passes each line to the status window as
   `dumpcap on <name>: <line>`: error messages, and the packet and drop
   counts `dumpcap` writes when it stops. It leaves out the two lines
   `dumpcap` writes on every start, even with `-q` (`DUMPCAP_START_LINES`:
   `Capturing on '<description>'` and `File: -`). The launcher's own
   `Capturing on <name> (<address>)` line already says the same thing, and
   `File: -`, read on its own, looks like a file being sent somewhere; it
   only means that the packets go to `dumpcap`'s stdout, the pipe into the
   launcher. Before this, `dumpcap` inherited the launcher's stderr and
   these lines showed up unmarked in the terminal.
3. It finds the prefix (`game_prefix`): from a running `AION2.exe`'s
   environment, else from the `libraryfolders.vdf` of each native Steam
   installation (`steam_roots`, §14). Then it installs
   `a2qlinux/bin/wpcap.dll` as `drive_c/windows/system32/Npcap/wpcap.dll`
   (`install_bridge_dll`). It replaces only an empty marker or an older build
   of ours, recognised by the string `questlog-proton bridge`
   (`BRIDGE_SIGNATURE`, kept from the project's first name: a new string
   would make an installed build look foreign). Any other file there, such as a real Npcap, is left
   alone and reported.
4. It starts Questlog in the prefix through protontricks
   (`launch_questlog`): `protontricks -c 'wine Questlog.exe …; echo $? >
   questlog.exit; wineserver -w'` in a systemd scope of its own, so that the
   launch outlives Questlog for as long as the Wine session is in use (§5.1,
   "The launch holds the session"). It passes:
   - `QUESTLOG_PROTON_BRIDGE=127.0.0.1:<port>:<token>`, read by the DLL;
   - `WINEDLLOVERRIDES=wpcap=n`, because Wine ships a builtin `wpcap` and
     loads it instead of a native file of that name, even when Questlog
     names our file by full path;
   - `--no-sandbox`, explained in §7.1.
5. Questlog finds the game's TCP connection itself (`GetExtendedTcpTable`;
   Wine reports connection owners correctly, as checked with
   `tools/tcp_owner_probe.c`). It lists the devices (`pcap_findalldevs`) and
   opens the one whose address is the connection's local address. Our DLL
   answers the list by asking the bridge (`QLPB2 <token> list`): one device
   per captured interface, named `\Device\NPF_A2Qlinux_<interface>`, with
   that interface's address. `pcap_open_live` connects again, sends
   `QLPB2 <token> open <interface>`, and receives `OK` followed by that
   interface's pcap file header, or `ERR <reason>`, which Questlog shows
   (the requests: §4.1).
6. Every 25 ms Questlog calls `pcap_next_ex` until it returns 0 and
   reassembles the TCP streams itself. Packet times come from the record
   headers, i.e. from when `dumpcap` captured them. `dumpcap` writes
   nanosecond timestamps; the server converts them to microseconds, which is
   what Questlog reads.
7. On a zone change Questlog opens a new device before closing the old one.
   The server serves any number of connections, each with every packet of
   its interface. A
   connection that stops reading (`CLIENT_QUEUE_RECORDS`, 5000 records
   queued) is dropped with a message; Questlog reopens it within a second.
   The status window names the interface Questlog follows
   (`Questlog follows the game's connection on wg0 (10.2.0.2).`) on its
   first connection and whenever the interface changes; the reconnects that
   every zone change brings are normal and pass silently, while a refused or
   dropped connection is always logged.

### 4.1 The DLL's calls

| Call | Behaviour |
|---|---|
| `pcap_findalldevs` | asks the bridge on every call; one device per captured interface, with its IPv4 address (an empty list when none is captured); without `QUESTLOG_PROTON_BRIDGE`, the error "No capture bridge: start Questlog with A2Qlinux", which Questlog shows |
| `pcap_open_live` | connect to the bridge, authenticate, ask for the device's interface, read the pcap header; the bridge's `ERR` reason becomes the error Questlog shows |
| `pcap_next_ex` | 1 = packet, 0 = none waiting (non-blocking), -1 = connection lost, reason in `pcap_geterr` |
| `pcap_compile`, `pcap_setfilter`, `pcap_freecode` | accepted, no effect; `dumpcap` already filters |
| `pcap_datalink` | the link type from that interface's pcap header: 1 on Ethernet, 101 (raw IP) on a WireGuard VPN |
| `pcap_setnonblock`, `pcap_geterr`, `pcap_close`, `pcap_freealldevs`, `pcap_lib_version` | as in libpcap |

The first call to `pcap_findalldevs` or `pcap_open_live` also starts the
window-order guard (§6.1).

**Bridge requests.** Each DLL connection to `BridgeServer` sends one line,
`QLPB2 <token> <request>`, and gets one of these answers (the code's copy of
this contract is the docstring of `a2qlinux/pcap_bridge.py`):

| Request | Sent by | Answer |
|---|---|---|
| `list` | `pcap_findalldevs` | `<interface> <IPv4>` per captured interface, one per line, then an empty line; the server closes |
| `open <interface>` | `pcap_open_live` | `OK`, the interface's 24-byte pcap header, then its records for as long as the connection lives; or `ERR <reason>` and the server closes |
| anything else, a wrong token, or `QLPB1 …` (the one-device protocol before November 2026) | — | the connection is closed and the refusal logged |

The list needs the token too: interface names and addresses are not given
to programs that cannot also read the traffic (I4).

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

### 4.3 Several interfaces: the network card and a VPN

**Why every interface.** With a VPN on, the game's connection runs from the
VPN interface's address through that interface (measured here with Proton
VPN, whose WireGuard interface is `proton0`, address `10.2.0.2`). Nothing in
the code depends on a VPN's name or kind: interface names differ between
VPN programs (`wg0`, `tun0`, `proton0`, `tailscale0`, …), and every
interface with an IPv4 address is captured. The network card carries the same traffic
encrypted, of no use to Questlog. With the VPN off it runs through the
card. The launcher cannot know in advance which one: before the game starts
there is no connection to look at, a VPN can go up or down in the middle of
a session, and with split tunnelling the default route says nothing about
the game. So the launcher does not choose. It captures on every interface
and leaves the choice to Questlog, which has the one fact that decides it:
the local address of the game's connection.

**How Questlog chooses** (read in its capture worker, `combat.cjs`): on
each pass over the game's connections it groups them by local address. For
an address that has no open device yet it lists the devices anew and opens
the one whose addresses include it (`addresses.includes(<local address>)`),
as it does on Windows among Npcap's adapters. If none does, it records
"Npcap lists no adapter with this address" for that address and tries again
on the next pass, with a fresh list. A device that appears later is
therefore picked up without a restart, and a device that is withdrawn ends
its connection (`pcap_next_ex` returns -1), after which Questlog lists
again.

**What `Captures.scan` does**, at start and then every `CAPTURE_SCAN_EVERY`
(3 s) from the launcher's main loop:

1. Read the interfaces that are up with an IPv4 address (`usable_interfaces`:
   `if_nameindex`, then `SIOCGIFADDR` per name), keeping only those named in
   `interface` / `--interface` when that is set.
2. Interface gone (a VPN switched off): stop its `dumpcap` and withdraw the
   channel (`BridgeServer.remove_interface`, which disconnects its clients,
   so Questlog lists again). Status window:
   `Interface wg0 is gone (a VPN switched off?); capture there stopped.`
   This is normal and raises no notification.
3. Address changed (a new DHCP lease, a VPN reconnecting): stop and start
   again, since the address is part of `dumpcap`'s filter. Status window:
   `Interface <name> changed its address from <old> to <new>; capturing there again.`
4. Interface created anew under the same name (`interface_index` differs
   from the one recorded at the capture's start): stop and start again.
   Status window: `Interface <name> was created anew (a VPN reconnecting?);
   capturing there again.` No notification. This is the case of Proton VPN
   switching servers: NetworkManager deleted `proton0` and created it again
   0.6 s later with the same address (journal, 8 November 2026), between two
   scans, so step 2 never saw it gone. `dumpcap` ends with the deleted
   interface ("The network adapter … is no longer attached"). The kernel
   gives a recreated interface a new index, while a link going down and up
   keeps its index and `dumpcap` runs on through it (both measured with a
   dummy interface in a private network namespace, `unshare -rn`).
5. `dumpcap` ended by itself while its interface is still up, with the same
   index: status window `Capture on <name> (<address>) ended: …`, with the
   exit code and a pointer to `a2qlinux-setup`; `dumpcap`'s own message
   (`dumpcap on <name>: …`, if it wrote one) is the line before it: the scan
   waits up to a second for that interface's message thread to finish before
   it writes its own line. One desktop notification. The interface is tried
   again every `CAPTURE_RETRY_EVERY` (30 s), and at once when its address
   changes; a repeated failure on the same interface and address is not
   reported again, so a permission problem gives one message, not one every
   30 s. The launcher keeps running: other interfaces may still carry the
   game. (Before this design a stopped `dumpcap` ended the launcher; with
   several interfaces one failure must not take the others down.)
6. New interface: register the channel, start `dumpcap`. Status window:
   `Capturing on <name> (<address>), TCP port 13328.`
7. Nothing up: `No network interface with an IPv4 address is up; capture
   starts as soon as one is.`, once. An interface named in the settings
   that is not up: one line per name, again only after it has been up.
8. **Where the game is** (`game_connection_addresses`): read the kernel's
   `/proc/net/tcp` for established connections to port 13328. A local
   address that no capture covers (the setting excludes its interface, or
   capture there failed) is logged with what is captured instead, and
   notified, once each time it appears. This check is what made the
   recreated-interface case of step 4 visible before step 4 existed.
   An address that no interface has at all is a different case, told
   differently (`AION 2's connection to its server still uses <address>,
   which no network interface has any more …`): the kernel keeps a
   connection "established" after its local address has gone, until the
   program gives up on it. Seen when the VPN was switched off during play
   (8 November 2026): the game's connection stayed on `10.2.0.2` with a
   growing send queue (13,937 bytes, then 21,112), the game froze, and it did
   not reconnect by itself. Nothing passes on such a connection, with or
   without A2Qlinux, which only reads a copy of the traffic; the message
   names the cause instead of pointing at the settings. Without this, Questlog's own message
   would be the only sign. The game runs in Steam's runtime container, which
   shares the host's network namespace, so its connections are in that
   table (seen: the game's connection from `10.2.0.2`).

**Link types.** `dumpcap` writes each interface's own link type into its
pcap header, and the DLL reports it from `pcap_datalink`. Questlog's frame
decoder reads Ethernet (1), BSD loopback (0, 108) and raw IP (12, 101), and
skips any other frame without a word. `pump_records` therefore logs an
interface whose link type is outside `QUESTLOG_LINKTYPES`
(`Interface <name> delivers link type N, which Questlog cannot read …`).
Measured on the kinds of interface VPNs use, created in a private network
namespace (`unshare -rn`): `tun` (OpenVPN in tun mode and many commercial
VPNs) and WireGuard deliver 101, `tap` (OpenVPN in tap mode) delivers 1;
with the game, the network card `enp9s0` delivered 1 and Proton VPN's
WireGuard `proton0` 101. All are in `QUESTLOG_LINKTYPES`; a kind outside it
would show as that line.

**Cost.** One `dumpcap` per interface. With the filter, an interface without
game traffic delivers nothing (measured: 0 packets on `enp9s0` while the
game ran through `proton0`).

**Checked with the game** (8 November 2026, Proton VPN on): the real
`Captures` and `BridgeServer`, with `bridge/tests/bridge_client_test.exe` in
a throwaway prefix calling the DLL as Questlog does. The DLL listed
`enp9s0` (10.0.4.90) and `proton0` (10.2.0.2). Given the game connection's
address `10.2.0.2`, it opened `proton0` with link type 101 and received
1071 game packets in 20 s, with a mean delay of 138 ms and a maximum of
272 ms, the same as on the network card (§4.2). Given `10.0.4.90`, it
opened `enp9s0` with link type 1 and received nothing, as expected.
Then Questlog itself, started into the running game's session: it opened
`proton0` and recorded the character's session and four encounters, two
ending in a kill, all through the VPN. During a crowded event in that session
(about 600,000 logged events a minute, 1378 entities) the kills were saved
0.4–1.4 s after they happened, against 0.12–0.21 s in quieter fights
(§4.2). The difference is Questlog's processing under that load: the bridge
and `dumpcap` measured 138 ms on the same interface minutes earlier, and
the log held almost no repeated events (a few dozen in 20,000 lines), so
packets were not delivered twice.

**Rejected: choosing one interface at start** (by the game's connection or
the default route). There is no connection before the game starts, a VPN
switched during a session would leave Questlog on the wrong interface until
a restart, and with split tunnelling the default route is not the game's.
The earlier behaviour, refusing to start when more than one interface had
an address, left every VPN user editing the settings, and a setting naming
the VPN stopped working as soon as the VPN was switched off.

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

#### The launch holds the session

protontricks ends the Steam Runtime container of every call once the
call's command returns (`launcher_process.terminate()` in the `finally` of
its `run_command`), and everything started in that container goes with it.
Questlog's launch usually brings up the session: the `wineserver`, the
session's services (`services.exe`, `winedevice.exe`, `plugplay.exe`, …) and
the desktop process `explorer.exe /desktop` are all started from it and live
in its container. While Questlog was started as `protontricks-launch
Questlog.exe`, its call ended with Questlog, and a quit, crash or restart of
Questlog during play took the game's session along: the game froze
(10 November 2026, from **Quit Questlog** in the tray). A stand-in program
in place of the game showed the same, and the order of exits put the
container first: Questlog's call, its container, the `wineserver` and the
services all within the same 0.1 s. Killing only the `protontricks-launch`
process, so that its `finally` never ran, left the session running.

So `launch_questlog` runs Questlog as `protontricks
--no-background-wineserver -c 'wine Questlog.exe --no-sandbox; echo $? >
proton-stream/questlog.exit; wineserver -w' 3393110`:

- the shell writes Questlog's own exit code to `questlog.exit`, then
  `wineserver -w` waits until the session has ended, so the call, and the
  container holding the session, last as long as anything runs in it;
- `QuestlogLaunch` wraps the call for the launcher: `poll()`, `wait()` and
  `returncode` follow Questlog itself through that file, or the call if it
  ends first (protontricks failed), so the launcher's handling of Questlog
  ending (quit, restart after the game, update trial) is unchanged;
- `--no-background-wineserver`, because protontricks' background wineserver
  keeps a Windows program (`wineserver-keepalive.bat`) in the session until
  the call ends, and `wineserver -w` would wait for it for ever;
- the call runs under `systemd-run --user --scope` (`questlog-<pid>-<n>`):
  it stays the launcher's child, but in a cgroup of its own. The service
  `a2qlinux-steam` starts the launcher in kills what is left in its cgroup
  when the launcher exits, which would take the session along just the same.

A Questlog started again during play joins the running session. The calls
of earlier Questlog starts wait in their scopes until the session ends,
then end together with it. `show_questlog_window`'s second start, which
only hands a request to the running Questlog, keeps `protontricks-launch`
(`hold_session=False`): it must end at once.

Checked with a stand-in program for the game (10 November 2026): after
**Quit Questlog** the session, its services and the stand-in ran on;
Questlog started again from the menu joined the same `wineserver`; once the
stand-in ended, every waiting call ended within a second and nothing was
left. Checked with the game the same day: **Quit Questlog** during play, the
game ran on; Questlog started again from the menu read the game again (after
a zone change, see §7); after the game Steam was released as before (§6.7).

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
in `a2qlinux/launcher.py` reads that into `Requests`. The menu's first line,
greyed out, and the tooltip carry A2Qlinux's version (§12, "Shown
version"). The tray runs in its own
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

- `close-window` posts `WM_CLOSE` to the main window. Questlog treats it as
  a click on the window's X, and its own setting `closeAction` (in
  `AppData/Roaming/Questlog/state.json` in the prefix, chosen in its
  settings or by ticking "remember" in its close prompt) decides: `tray`
  hides the window; `quit` quits Questlog normally, with its own save
  (`will-quit`), so the launcher sees it end by itself within a second and
  ends too; `ask`, the default, shows Questlog's prompt in its window, which
  nobody sees while the window is hidden, and whose answer does not matter:
  `end-session` follows at the due time whatever it was. All three end
  without lost data (measured with `quit` on 10 November 2026: Questlog had
  gone 0.3 s after `close-window`; `ask` read from Questlog's code only).
  Questlog has no switch or message that makes it quit with its save from
  outside: its command-line switches are view, game, hidden and paths, a
  second start only shows its window (`second-instance`), and its other
  `app.quit()` is the Quit item of its own tray menu, drawn by Electron's
  own menu code and so not reachable by a window message.
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

A quit during play ends Questlog only. The game's Wine session stays,
because Questlog's launch waits for the session to end before its
container goes (§5.1, "The launch holds the session"); the game runs on, and
Questlog started again from the menu joins it. Questlog then shows the game
in full only after a zone change, which is when it learns the character
(§7).

Electron's auto-update would install on quit (`autoInstallOnAppQuit`); it is
switched off (§6.6), and the session end would skip it anyway.

### 6.5 Signals between the menu entry and the launcher

`a2qlinux/desktop.py` is what the menu entry, the desktop icon and
`a2qlinux-steam` run. If no launcher holds the lock, it opens
`a2qlinux/launcher.py` in a terminal window, the status window
(`terminal_command`, §14). Otherwise it signals the PID read from the lock file
(`launcher_pid`), after checking that the process's command line is the
launcher's, so a stale or reused PID is never signalled: it contains
`a2qlinux.launcher` (`python -m a2qlinux.launcher`, as the menu entry starts
it) or an argument named `a2qlinux-run` (the command run in a terminal; until
A2Qlinux 0.7.0 such a launcher was not recognised, so a click on the menu
entry did not reach it and `--diagnose` showed its PID as `None`):

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

### 6.8 Questlog's full-screen overlay layer on KDE Plasma

**Symptom.** On KDE Plasma, with the game full screen, the **Black Market
Cards** overlay (Questlog's notes drawn on the shop's own cards) and the
overlay controls icon never show, while the meter, alerts and the Black
Market panel do; and Questlog's overlay editing mode (Alt+E) shows only a
brief flash, with nothing to move.

**Cause.** Questlog keeps one transparent window over the game, the HUD
(class `steam_proton`, title `questlog.gg - Wiki, Builds, Guides, Database and
Tools for Aion 2`, Questlog's default page title, ex-style `WS_EX_TOPMOST |
WS_EX_NOACTIVATE | WS_EX_LAYERED | WS_EX_TRANSPARENT`). Each overlay widget
gets a small window of its own, owned by the HUD, but the cards and the
controls icon are drawn in the HUD itself, which covers the whole screen,
and so is every widget while the editing mode is on (Questlog's renderer
opens a widget's own window only outside editing).
In Wine's own window order the HUD is above the game. winex11 hands a popup
window that covers the whole screen to the window manager (a *managed* X
window); small owned popups stay *unmanaged* (override-redirect) and so
above everything. KWin puts the active full-screen game in its active
layer, above any managed window that is not active, so the game hides the
HUD. Measured with a test program in a throwaway prefix under `xvfb-run`
with Proton's Wine (9-10 November 2026): a full-screen popup became
managed, one a pixel shorter stayed unmanaged, and a window that had once
been managed stayed managed after shrinking, and after hiding, shrinking
and showing again. Nothing outside Questlog's browser process, which
creates the HUD, can change that.

**Remedy, KDE Plasma 6 only** (`a2qlinux/kde_overlays.py`), set up by
`a2qlinux-setup` with the user's consent:

- a KWin window rule `a2qlinux-questlog-hud` in `~/.config/kwinrulesrc`,
  appended to the rule list `Order` (KWin 6.8 reads that list; a rule in
  `rules` alone was not applied, checked through the window's `layer` as a
  KWin script reads it). It matches class `steam_proton` exactly and the
  title by the substring `questlog.gg - Wiki`, forces the layer `overlay`
  and never gives the window focus. Questlog's main window is titled
  `Questlog` and is not matched.
- a KWin script `a2qlinux-questlog-hud` in `~/.local/share/kwin/scripts`,
  enabled in `kwinrc` (`[Plugins]`). The rule alone left the cards above
  other programs after Alt+Tab with the shop open, since Questlog relies on
  the HUD being ordered just above the game. The script sets the HUD's
  opacity (compositor-side; Wine and Questlog do not see it) to 1 while the
  active window is AION 2 (`steam_app_3393110`) or the HUD, else to 0. A
  script cannot set the layer itself: KWin's `Window.layer` is read-only.

Both act on the HUD alone, matched by class and title, which keeps I2: the
game, Questlog's other windows and other programs' windows are neither
matched by the rule nor changed by the script, which only reads which
window is active. The rule list is appended to, never rewritten, so other
programs' rules (A2Tools adds three) stay as they were.

`a2qlinux-setup` on Plasma 6 (`XDG_CURRENT_DESKTOP` contains `KDE`,
`KDE_SESSION_VERSION` at least 6) explains this and asks, with yes as the
default; without a terminal it only names `--kde-overlays`. Once set up, a
later run refreshes both pieces without asking. `--kde-overlays` sets up
without asking, `--no-kde-overlays` removes: the rule's keys and its name in
`Order`, the `kwinrc` entry, the script (unloaded by name over D-Bus: a
reload alone left it running once its files were gone) and its folder, and
a one-off script sets the HUD's opacity back to 1. KWin is reloaded over
D-Bus (`org.kde.KWin.reconfigure`) each time. Checked on this desktop
(10 November 2026): install, cards shown, cards hidden over other programs, Alt+E editing
usable over the game (overlays moved),
removal left `kwinrulesrc` byte for byte as before and the HUD back below
the game.

On every other desktop, Plasma 5 included, nothing is written and the
overlays behave as before. Whatever fails here (a tool missing, KWin
refusing, a Questlog update changing the HUD's title so the rule no longer
matches) leaves the overlays as they were and nothing else changes; the
setup reports it as a note, not as a problem. The one case worse than
before: the rule working without the script, which leaves the cards above
other programs after Alt+Tab with the shop open, until the shop is closed.

**Cost.** GPU load and power with the game standing still, 15 s each, the
HUD below the game, above it, below again: 42 % and 133 W in all three
(RTX 3060 Ti, the game's frame rate capped). Questlog's widget windows
already sit above the game, so KWin composites over it in any case.

**Rejected.** Wine's `Managed` setting for Questlog alone
(`AppDefaults\Questlog.exe\X11 Driver`) would also unmanage Questlog's main
window, which then could not take keyboard focus. A HUD a pixel smaller
than the screen would stay unmanaged and fix this on every desktop; that is
Questlog's code, so it is a request to Questlog, not something A2Qlinux can
do.

### 6.9 A Questlog that hangs at its start

**Symptom** (seen once, 12 November 2026). Questlog's
main process runs and even hides its tray icon on request, but its window
stays empty or does not come, the status window never says "Questlog
follows the game's connection", and there are no fights. Only two
`Questlog.exe` processes exist instead of the usual ten or so, and neither
is a GPU process, a renderer or a utility.

**Cause** (a stack taken with `gdb` from the second process). That process
is a copy of Questlog's main process that Wine had forked to start
Questlog's first own process, the GPU process: one thread, the main
process's memory and command line, stuck in `__lll_lock_wait_private` ←
`unsetenv` ← `exec_wineloader` ← `NtCreateUserProcess` (Proton's
`ntdll.so`). Wine changes the environment in the forked copy before it
runs the new program. glibc's lock on the environment is not reset by
`fork`, so when another of Questlog's threads held it at the moment of the
fork, the copy waits for a lock that no thread in it will ever release.
Questlog waits for its GPU process for ever. A race in Wine, not something
A2Qlinux or another program can cause: the lock lives in Questlog's own
memory.

**What the launcher does.** Every start of Questlog goes through
`start_questlog` (the first, the restart after the game, a start when
Questlog was asked for again while a quit was ending it, the first start
after an update), and
each arms `StartWatch`. Until the watch has answered, the main loop reads
Questlog's processes every 0.5 s with `questlog_process_states`: PID,
whether the command line carries Chromium's `--type=` (GPU, renderer,
utility processes do; the main process does not), and the thread count.

A *stuck copy* (`stuck_copies`) is a Questlog process without `--type=`
and with a single thread, seen beside a main process that has threads of
its own. The second condition keeps a main process that has not started
its threads yet from being taken for one. A copy that Wine forks normally
becomes the new program within a fraction of a second, so one that lasts
seconds is a hang.

The watch answers once per start:

| Answer | When | What follows |
|---|---|---|
| `up` | any process with `--type=` is there | nothing; the count of hung starts goes back to 0 |
| `retry` | the same stuck copy has lasted `STUCK_WAIT` (3 s), or no process with `--type=` came within `START_WAIT` (30 s) | Questlog is ended and started again on the same bridge, hidden if the hung start was |
| `give-up` | as `retry`, for the `START_ATTEMPTS`-th (2nd) start in a row | Questlog is ended, a notification is shown, the launcher ends with code 1 |

Both waits count from the moment Questlog's main process appears, not
from the start call, so bringing up the Wine session and installing an
update do not use them up. Measured on a healthy start: the GPU process
1 s after the main process, all ten processes after 3 s. The 12 November
hang would have been acted on about 4 s after Questlog's main process
appeared, by `STUCK_WAIT`. `START_WAIT` is for any other way a start
could hang. It is long because without a stuck copy a hang cannot be told
from a slow start (a cold disk after a reboot, heavy swapping), whose
length has not been measured, and too short a wait would end a healthy
start twice and then give up.

`end_hung_questlog` sends SIGTERM to all of Questlog's processes, stuck
copies included, and SIGKILL to any still there after `HUNG_END_WAIT`
(5 s). Questlog has got no game data yet, so nothing is waiting to be
saved. The session end of §6.4 is not used: sent to a Questlog that was
still starting, it was ignored for the whole `QUESTLOG_QUIT_WAIT` (20 s,
measured). The game is not touched, since Questlog's launch holds the
session (§5.1); only Questlog's processes are signalled (I2).

What the status window shows:

```
Questlog hung at its start: Wine's start of its first own process hung
  (stuck process 23549). Ending it and starting it again.
Questlog's 2 process(es) ended.
Starting Questlog 0.1.51.
```

Without a stuck copy the reason reads "none of its own processes followed
within 30 s". On `give-up` the first line is "Questlog hung at its start
again (2 starts in a row): …", followed by what to do.

**Checked** on 12 November 2026, with the game running. Ending the stuck
copy by hand made Questlog exit by itself (code 0) within seconds, and
the game ran on; Questlog started again from the menu came up normally.
The retry and the give-up were run the same day by setting `START_WAIT`
to 0 for the test, so that every healthy start looked hung: both starts
were ended within 0.1 s, the launcher ended with code 1 with its window
left open, and the game ran on. A real stuck copy has not met this code
yet. Each start's launch waits in its scope until the session ends
(§5.1), so after a retry two launches wait instead of one; they end with
the session.

**Why not the capture as the sign.** The DLL talks to the bridge only once
Questlog has found the game's connection (§4, step 5), so without the game
a healthy and a hung Questlog look the same. The utility process with the
combat worker (`node.mojom.NodeService`) is no sign either: Questlog starts
it on demand and stops it 30 s after its last user (`hold()` in its
`main.cjs`). The GPU process is started with the app, and is the one
whose start hung.

**Not covered.** A start of a later process (a renderer, the combat worker)
could hang in the same way while Questlog runs; not observed. The watch
answers once per start, and only `up` resets the count.

### 6.10 Questlog's "Open Folder" buttons

**Symptom.** Questlog's **Open Folder** button (Combat Meter, the list of
recordings) shows Wine's message "There is no Windows program configured
to open this type of file", and no folder opens.

**Cause.** The button runs Questlog's `openRecordings`, which creates
`recordings` under Questlog's data folder (`C:\users\steamuser\AppData\
Roaming\Questlog`) and passes it to Electron's `shell.openPath`. For a
folder, Electron calls Chromium's `ui::win::OpenFolderViaShell`, which is
`ShellExecuteExW` with the verb `explore`, the class `folder`
(`SEE_MASK_CLASSNAME`), the folder as an item id list (`SEE_MASK_IDLIST`)
and `SEE_MASK_NOASYNC`. With an explicit class, Wine's `shell32` looks the
verb up under `HKCR\folder\shell\explore\command`. Proton's `wine.inf`,
like Wine's, registers only `folder\shell\open\ddeexec`, so the lookup
fails and `shell32` shows the message. Without a class, the same folder
opens: Wine then falls back to its own `explorer.exe`. Measured with a test
program making Chromium 152's call (Questlog 0.1.51 ships Electron 44.5.1)
under `xvfb-run` with Proton's Wine (13 November 2026): it failed in a
fresh prefix and in one holding a copy of the game prefix's registry, and
succeeded once the key existed. The same call without class and verb
succeeded in both. It is Wine's gap, not something A2Qlinux causes.

**Remedy** (`a2qlinux/open_folders.py`, `questlog_ctl.exe folder-handler`),
set up by `a2qlinux-setup` with the user's consent: the one missing command,
`HKLM\Software\Classes\folder\shell\explore\command` =
`"C:\windows\system32\winebrowser.exe" "%1"`, the command the prefix already
has for web links (`http`, `https`, `ftp`). `winebrowser` turns the
Windows path into a `file://` URL of the Linux path and runs `xdg-open`.
Questlog runs inside Steam's runtime container, where `xdg-open` is
`steam-runtime-urlopen`; that hands the URL to the desktop outside, and
the folder opens in the desktop's file manager (checked on this desktop,
13 November 2026: Dolphin).

The registry is read and written by `questlog_ctl.exe` inside the prefix
(`protontricks-launch`, like its other commands). That way the check sees
the registry the `wineserver` holds in memory, the one Questlog's call
reads, also while the game runs, and nothing writes the registry files
behind the `wineserver`'s back. The command does one of three things:

- `status` prints `absent`, `ours` (exactly the value above) or `other`
  (anything else there, a key without a default value included);
- `set` writes the value only when it is `absent`;
- `remove` deletes `command` only when it is `ours`, then the verb's key
  `explore` if nothing else is left in it.

The first word printed is the outcome; `open_folders.outcome` reads it.

`a2qlinux-setup` (`open_folders.setup_step`) runs `status` first. On
`absent` it shows `EXPLANATION` and asks once, yes being the default;
`--open-folders` sets up without asking, `--no-open-folders` runs
`remove`, and without a terminal it only names the option. What it prints:

| State before | Setup prints |
|---|---|
| `absent`, answered yes | `Open Folder: set: folders now open through winebrowser.exe (…)` |
| `absent`, answered no | `Not set up; run a2qlinux-setup --open-folders to do it later.` |
| `ours` | `Open Folder: Questlog's folders open in the file manager.` |
| `other` | `Open Folder: the prefix already has a command for opening folders; A2Qlinux leaves it (…)` |
| any, `--no-open-folders` | `Open Folder: removed: …`, `absent: nothing to remove.` or `other: … left as it is.` |

Failing (no prefix yet, `protontricks-launch` missing, no answer within
`CTL_WAIT`) is printed as `Note: Open Folder: …` and is not a problem:
only the button depends on it. The change takes effect at once, with
Questlog open: `shell32` looks the verb up at each call. `a2qlinux
--diagnose` reports the same three states without starting Wine (§9.1).

**Reach.** The key is prefix-wide (I2's exception): any program in the
prefix that opens a folder with `explore` and the class `folder` now gets
the file manager instead of the error. Neither the game nor NotMeter is
known to make that call. Proton keeps the key when it updates the prefix:
its `wine.inf` has no `DelReg` section, and the `proton` script deletes only
the keys it lists in `delete_dde_keys` (`ddeexec` of web links and
document types) and `delete_keys` (one service).

**Rejected.** Redirecting the call inside Questlog alone, by patching
`ShellExecuteExW` in `Questlog.exe`'s import table from our `wpcap.dll`:
it touches no prefix setting, but it is an API hook in a closed program,
tied to how Chromium makes the call. Editing `system.reg` from Linux:
a running `wineserver` holds the registry in memory and writes its own
copy back, so the change could be lost.

### 6.11 A Questlog left by an ended launcher

**Symptom.** The status window was closed while Questlog ran. Questlog
stays open but counts nothing, and neither tray icon is there to quit it.
`a2qlinux --diagnose` says `PROBLEM  Now: Questlog runs with the bridge,
but A2Qlinux has ended`. Until A2Qlinux 0.7.0, starting A2Qlinux again
then ended at once with "Questlog is already running and fed by another
A2Qlinux", which was false (reported in issue #2).

**Cause.** Closing the terminal sends the launcher SIGHUP, which ends
Python without a word (nothing reaches `launcher.log`). Questlog's launch
is a scope of its own (§5.1) and runs on. Its bridge is gone, its own
tray icon was hidden by `hide-tray` (§6.2), and ours ended with the
launcher.

**Behaviour.** A launcher that has taken the lock (I1) looks at the
running Questlog's environment (`running_questlog_state`):

| Found | Meaning | What the launcher does |
|---|---|---|
| no Questlog | — | starts it |
| `QUESTLOG_PROTON_BRIDGE` set (`orphaned`) | started by a launcher that has ended, since none other can run | `end_orphaned_questlog`, then starts it |
| not set (`outside`) | started without A2Qlinux | stops: "already running in the game prefix without the capture bridge" |

`end_orphaned_questlog`, in order:

1. Logs `Questlog is still running from an A2Qlinux that has ended (its
   status window was closed?) … Closing it in 10 s, once it has saved,
   and starting it again.`
2. Waits `SAVE_WAIT` (10.5 s): Questlog saves every 10 s, so what it
   received before its bridge went away is written.
3. Sends `end-session` to Questlog's main window (§6.4); the game is not
   touched. When that fails (a hung window does not answer
   `SMTO_ABORTIFHUNG`), it logs `Questlog did not take the session end`
   and goes on.
4. `wait_for_questlog_exit` waits `QUESTLOG_QUIT_WAIT` (20 s) for
   `Questlog closed.`, else stops the processes with SIGTERM.
5. Waits up to `ORPHAN_EXIT_FILE_WAIT` (5 s) for the old launch to write
   `questlog.exit`. `launch_questlog` deletes that file before its own
   launch; written after that, it would read as the new Questlog's end.
6. If a `Questlog.exe` still runs, stops with "could not be closed";
   otherwise the start continues as usual (`Capturing on …`, `Starting
   Questlog …`).

The previous run's `questlog.log`, with the orphan's output, is kept as
`questlog.log.1` (§9). Checked on this desktop (13 November 2026): SIGHUP
to a running launcher, `--diagnose` showed the `PROBLEM`, a second
launcher closed the orphan after 10 s and started Questlog with its own
bridge; quitting afterwards left nothing behind. The same with the game
running (13 November 2026): `AION2.exe` kept its PID throughout, and the
new Questlog logged "follows the game's connection" and "Game traffic is
flowing to Questlog", so it joined the game's session. The hung case, with a
stand-in `Questlog.exe` whose window stops answering after 3 s, in a
throwaway prefix under `xvfb-run`, through the shipped
`end_orphaned_questlog` (only `protontricks-launch` and the process lookup
pointed at that prefix): `end-session` failed with error 1460 (timeout),
`wait_for_questlog_exit` stopped the process with SIGTERM after 20 s, and
the function returned with nothing left running.

**Not changed.** Closing the status window still ends the launcher.
Keeping it alive instead would mean a launcher that runs on without its
terminal, which nothing in it is built for; that is a separate change,
not made here.

## 7. Failure modes

| Symptom | Cause | Where to look |
|---|---|---|
| Questlog quits at once, "GPU process isn't usable" | Chromium's sandbox inside Steam's container (§7.1) | `questlog.log` |
| "Questlog hung at its start: … Ending it and starting it again." | Wine's start of Questlog's first process hung (§6.9) | none; "stuck process" names the copy that hung |
| "Questlog hung at its start again …" (notification), launcher ends with code 1 | the start hung twice in a row (§6.9) | start again from the menu; `questlog.log`, a problem report |
| Questlog shows "No capture bridge: start Questlog with A2Qlinux" | Questlog started without the launcher | start it from the menu entry |
| "Capture bridge not reachable (is A2Qlinux running?)" | launcher not running (terminal closed) | status window |
| "Questlog is still running from an A2Qlinux that has ended …" | the status window of the launcher that started it was closed (§6.11) | none: it is closed after `SAVE_WAIT` and started again |
| "Questlog keeps running from an A2Qlinux that has ended and could not be closed" | the orphan survived `end-session` and the stop of its processes (§6.11) | `questlog.log`; its `Questlog.exe` processes |
| "Capture bridge closed the connection …" | launcher stopped, or it dropped a connection | status window |
| Questlog: "Npcap lists no adapter with this address" | the game's connection uses an address no capture covers | status window: "AION 2's connection … uses …, which A2Qlinux does not capture on" (§4.3, step 8) |
| "AION 2's connection … still uses …, which no network interface has any more" | the VPN was switched off under a running game; its connection is dead until the game reconnects | none on our side; the game has to reconnect (§4.3, step 8) |
| Questlog: "A2Qlinux does not capture on <name> (any more) …" | the interface went away between Questlog's list and its open | none; Questlog lists again on its next pass |
| "Capture on <name> … ended" (and a notification) | `dumpcap` failed on that interface, usually capture permission | `dumpcap on <name>: …` above it (`dumpcap`'s own line); `a2qlinux-setup` |
| "Interface <name> delivers link type N, which Questlog cannot read" | an interface type Questlog's decoder skips (§4.3) | none from our side; game traffic on that interface is not counted |
| "Refused a connection … from an older A2Qlinux wpcap.dll" | a Questlog still running with the DLL of an older A2Qlinux | quit Questlog and start it through A2Qlinux |
| Steam "launching" forever while Questlog runs | Proton waiting for an idle prefix (§5.1) | `steam_launch.log`; set the launch option |
| click in the game activates Questlog | §6.1; guard not running | `questlog.log`, `[a2qlinux]` lines |
| two Questlog tray icons | `hide-tray` failed | status window, `Questlog control:` lines |
| "Aion 2's traffic can't be read" before logging in | §7.3, harmless | — |
| "A2Qlinux is already running in another window" | second launcher refused (I1) | use the running one |
| "Questlog is already running in the game prefix without the capture bridge" | Questlog started outside A2Qlinux | quit it from its own tray icon |
| Tracker Map overlay blank, and no fights in the meter ("Detecting character…"), after restarting Questlog mid-game | Questlog learns the character (`self`) and its zone only from the login (`Login_RS`) and map-enter (`PrepareEnterMap_NT`) packets; it flags the gap itself once positions or damage arrive for 5 s without a known character. The same on Windows | change zone, or log back in. Replaying earlier traffic from the launcher was rejected: without decoding it, only the whole stream since the connection began could be replayed, and Questlog would count old fights again and upload them again |
| Black Market Cards (and the overlay controls icon) never show over the full-screen game; Alt+E only flashes | KDE keeps the game above Questlog's full-screen HUD (§6.8) | `a2qlinux-setup --kde-overlays` on Plasma 6; elsewhere none |
| `a2qlinux-setup`: "Note: KDE overlays: …" | a tool or KWin refused (§6.8); nothing else is affected | the reason in the note |
| Questlog's Open Folder: "There is no Windows program configured to open this type of file" | the prefix has no command for opening folders (§6.10) | `a2qlinux-setup --open-folders` |
| `a2qlinux-setup`: "Note: Open Folder: …" | `questlog_ctl.exe folder-handler` could not run or failed (§6.10); nothing else is affected | the reason in the note |
| game froze after **Quit Questlog** during play (A2Qlinux 0.3.0 and earlier) | Questlog's launch ended and protontricks took the game's session down with its container (§5.1, "The launch holds the session") | update A2Qlinux |
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
`ws2_32`, `ucrtbase`, `shell32`, `advapi32`; `llvm-objdump -p`), so a Wine update needs
no rebuild. Observed: the build here against system Wine 11.21 runs daily
under Proton's Wine 11.0, and the PyPI package's parts are built against
whatever Wine the CI container has.

**Questlog in the game's prefix, not in one of its own.** A prefix of its
own would remove everything §5 and §6.7 deal with: the game would not wait
for Questlog (Proton waits only for its own prefix to go idle), so no
launch option, no closing and reopening around Play, no releasing Steam.
Questlog cannot work there, though. It finds the game through the Windows
process list (`CreateToolhelp32Snapshot`, `Process32FirstW`, looking for
`Aion2.exe` in its game definition); from the game's processes it finds the
game's window, which its overlays follow, and it checks the game's TCP
connections with `GetExtendedTcpTable`. Under Wine that process list holds
only the processes of the same `wineserver`, i.e. the same prefix.
Measured 10 November 2026 with two throwaway prefixes: `tasklist` in the
first listed its `cmd.exe` and `ping.exe`, in the second neither, only its
own nine processes. Questlog in a prefix of its own would never see the
game. Making it see the game would mean faking Windows' process list for
it, which is not worth the gain.

**The Steam launch option is checked, never written.** `a2qlinux-setup`
and `a2qlinux --diagnose` read AION 2's launch option and print the line to
paste (§9.1); A2Qlinux could also write it into `localconfig.vdf` itself,
which would remove the one manual step players skip (the first problem
report came down to it). Rejected on 10 November 2026: the launch option
is the player's own Steam setting, which they may want to keep as it is
or keep A2Qlinux out of, and the menu entry works without it (§5.2).

**Our tray instead of fixing the Wine one** — §6.2. **The guard instead of a
patched Proton** — §6.1. **Session end after a delay instead of an immediate
one** — §6.4.

## 9. Tests and diagnostics

| What | How |
|---|---|
| launcher, bridge, quit logic, updates, Steam verb switch | `python3 -m unittest` in the repository root (no built Windows parts needed; CI runs `bash bridge/build.sh` and the tests on every push, §12); the update tests build a fake installer with `7z` and run feed → download (`file://`) → checks → swap → rollback, and the first installation (`install_fresh`), offline |
| DLL against a live bridge | `bridge/tests/bridge_client_test.exe [<local address>]` in a throwaway prefix, with a running `BridgeServer` (with `Captures`, for real traffic), `WINEDLLOVERRIDES=wpcap=n` and `QUESTLOG_PROTON_BRIDGE` from `environment_value()`; it opens the device with that address, as Questlog does, or the first one; report in `C:\bridge_client_test.txt` (devices, link type, packets, delay) |
| window-order guard | copy `bridge/tests/zorder_guard_test.exe` and `a2qlinux/bin/wpcap.dll` to an empty folder, then `WINEPREFIX=<throwaway> xvfb-run -a wine zorder_guard_test.exe 'Z:\<folder>\wpcap.dll'`; prints the order before and after, `PASS`/`FAIL` |
| `questlog_ctl.exe` by hand | `protontricks-launch --appid 3393110 <package>/a2qlinux/bin/questlog_ctl.exe hide-tray` (or `show-tray`, `close-window`, `end-session`, `folder-handler status`); `<package>` is printed by `python -c 'import a2qlinux; print(a2qlinux.__path__[0])'` in A2Qlinux's environment |
| `questlog_ctl.exe` without the game prefix | Questlog in a throwaway prefix: `wine Questlog.exe --no-sandbox --disable-gpu` under `xvfb-run`, then the commands through `wine` |
| who owns the game connection | `tools/tcp_owner_probe.exe` in the prefix |
| KDE overlays (§6.8) | `tests/test_kde_overlays.py` runs against stand-ins for KDE's config tools and `dbus-send`, and, where `kwriteconfig6` is installed, checks with the real tools that removal gives the rule file back byte for byte; on the desktop, a one-off KWin script that prints the HUD's `layer` and `opacity` shows what KWin applied |
| folder handler (§6.10) | `tests/test_open_folders.py` (the setup step against a stand-in for `questlog_ctl.exe`; `registry_state` on `system.reg` text as Wine saves it; the value in Python equal to the one in `questlog_ctl.c`); the command itself in a throwaway prefix: `WINEPREFIX=<throwaway> wine questlog_ctl.exe folder-handler status` (then `set`, `remove`), and a test program making Chromium's call (`ShellExecuteExW`, verb `explore`, class `folder`, `SEE_MASK_IDLIST`) with a stand-in `xdg-open` first in `PATH` that records its argument |
| does the session survive a quit (§5.1) | without the game: a Windows program that only waits, started as `systemd-run --user --unit=<name> protontricks-launch --appid 3393110 <program>.exe`, plays the game; quit Questlog and check that the program, the `wineserver` and `explorer.exe /desktop` run on, and which unit holds them (`/proc/<pid>/cgroup`) |
| a stuck process (§6.9) | `gdb -p <pid> -batch -ex bt` as root (`ptrace_scope` 1 allows a user to trace only their own children); A2Qlinux never does this itself |
| Wine's view of windows and focus | run `WINEDEBUG=+event,+x11drv,+win a2qlinux-run`; the log grows about 40 KB/s, so only briefly |

Logs: the launcher's messages in its status window (the terminal), and the
same lines with the time to the millisecond in `proton-stream/launcher.log`
(`LogFile` in `a2qlinux/launcher.py`). The window closes by itself when the
launcher ends normally, and before the file existed that took the only
record of what the launcher had done; a quit that went wrong could then be
read only from systemd's journal, which shows when Questlog's scopes
(`questlog-<launcher PID>-<n>`) started and ended but not why. Each run
starts with `A2Qlinux <version> (launcher PID <pid>).`, so a run in the
file can be matched to those scopes. Lines logged before the lock is taken
(settings problems, the version line) are held and written once it is; only
the launcher holding the lock writes the file. When the file passes
`LAUNCHER_LOG_LIMIT` (1 MB, some ten thousand lines, many days of play) it
becomes `launcher.log.1`, replacing the one before, so at most 2 MB are kept.
A file that cannot be written is said once in the window. Not recorded: a
launcher ended by closing its window (SIGHUP ends Python without a word) and
Python tracebacks, which only the window shows. Questlog's and Wine's
output, including the guard's lines, is in `proton-stream/questlog.log`,
begun anew on each launcher start (`start_questlog_log`), the previous
run's kept as `questlog.log.1`, so that restarting A2Qlinux after a problem
does not empty the log that shows it (an empty run does not replace it);
Steam verb switches in
`proton-stream/steam_launch.log`.

The test programs use `xvfb-run` so that they take no focus on the desktop.
Throwaway prefixes keep the game's prefix free of anything but A2Qlinux's
own files.

### 9.1 `a2qlinux --diagnose` and problem reports

**Why.** When a player reports a problem, the facts that decide it are
spread over Steam's settings, A2Qlinux's files and the process table, and
until now had to be collected by hand with commands written for one
machine. The first such report (10 November 2026: the game would not start
while Questlog was open) came down to the Steam launch option not being set,
which no part of A2Qlinux checked.

**What it does** (`a2qlinux/diagnose.py`, answered by `a2qlinux` itself,
like `--version`, without opening a status window). It only reads, so it is
safe at any time, the game running or not. In order:

1. A2Qlinux's version (`shown_version`, §12); the system, graphics and
   screens (table below); the settings file and its problems, Questlog's
   folder and version.
2. The checks `a2qlinux-setup` makes, by calling the same functions
   (`missing_packages`, `capture_problem`, `tray_problem`,
   `windows_parts_problem`): there is one implementation of each.
3. Steam (`steam_roots`, the Flatpak case of §14), the game's prefix
   (`game_prefix`), the Proton that last ran it, Wine's DPI and the
   environment (table below), and whether the `wpcap.dll` there carries
   `BRIDGE_SIGNATURE`.
4. AION 2's launch option, from every Steam account's
   `userdata/<id>/config/localconfig.vdf`, path
   `UserLocalConfigStore > Software > Valve > Steam > apps > 3393110 >
   LaunchOptions`. `parse_vdf` reads Steam's KeyValues text format with
   keys lower-cased, since Steam writes `apps` and `Apps` in different
   places. `judge_launch_option` tells apart: not set (a note: the fallback
   of §5.2 still lets the game start); without `a2qlinux-steam`; no
   `%command%` (the game never starts); `a2qlinux-steam` without its
   folder (Steam does not find it, §5.1); a path that does not exist; a
   path that is another installation's. Words before it, such as
   `PROTON_FSR4_UPGRADE=1`, are left alone. `a2qlinux-setup` uses the same
   judgement at its end (`launch_option_step`): "set", or the line to paste,
   or a problem when the option keeps the game from starting. Steam
   writes the file within a second of each change in that field while it
   runs (measured 10 November 2026 by watching the file while the option
   was edited in Steam), so what is read is what Steam uses. Then the last
   line of `steam_launch.log`: whether the option ever ran, and how.
5. What runs now: the launcher (`launcher_running`, `launcher_pid`),
   Questlog and whether it carries `QUESTLOG_PROTON_BRIDGE` (one that does
   not was started outside A2Qlinux: it gets no traffic, and the game waits
   for it, §5.1), and the game.
6. On Plasma 6, whether the KDE overlays are installed (§6.8).
7. Whether the prefix has the command for Questlog's Open Folder buttons
   (§6.10): `open_folders.registry_state` reads it from the prefix's
   `system.reg` as text, with the same three answers as
   `questlog_ctl.exe folder-handler status`. Starting Wine instead would
   no longer be only reading: with no session running, it starts one in
   the game's prefix. The cost is lag: the `wineserver` saves a registry
   change to the file some 30 s later (26 s measured, 13 November 2026,
   with a session running), so a change made just now may not show yet;
   the `absent` note says so.

The lines that describe the machine rather than A2Qlinux. They exist so
that a report from another system can be compared with one where things
work: how windows, the tray and overlays behave depends on the desktop
(§6.8, §14), and Questlog draws its windows with Chromium on the GPU
(Direct3D 11 through DXVK under Proton), so a window that stays black is
first a question of card and driver.

| Line | Function | Read from | Notes |
|---|---|---|---|
| `System:` | `system_lines` | `PRETTY_NAME` of `/etc/os-release` (else `NAME` `VERSION_ID`); `platform.release()` | |
| `Desktop:` | `system_lines` | `XDG_CURRENT_DESKTOP`, `XDG_SESSION_TYPE`; version from the command in `DESKTOP_VERSION` (`plasmashell --version`, `gnome-shell --version`) when that desktop runs | |
| `Graphics:` | `gpu_lines`, `pci_name` | each `card<N>` under `/sys/class/drm` (connectors such as `card1-DP-1` skipped): `vendor`/`device` ids named from `pci.ids`, the kernel driver (the `driver` link), "primary" from `boot_vga`; NVIDIA's version from `/proc/driver/nvidia/version` | hex ids when `pci.ids` has no entry |
| `OpenGL:` | `gpu_lines` | `glxinfo -B`, where installed: renderer and version (Mesa's version on AMD and Intel) | `note` for `llvmpipe`, `softpipe`, `swrast`: no graphics driver in use |
| `Monitors (as Wine sees them):` | `display_lines` | `xrandr --listmonitors` | Wine draws through X11 (XWayland under Wayland), so this is where Questlog places its overlays |
| `Desktop scale:` | `display_lines` | KDE: `kscreen-doctor -j` (enabled outputs); GNOME: `<scale>` in `~/.config/monitors.xml` | GNOME without that file: never changed, 1 |
| `Proton (last run):` | `proton_line` | `config_info` beside the prefix, and the `version` file of the tool folder its paths lie in | see below |
| `Wine DPI:` | `wine_dpi_line` | every `LogPixels` under `Control Panel\Desktop` and `Software\Wine\Fonts` (`user.reg`) and both `Hardware Profiles` keys (`system.reg`) | each with its key: which one Wine applies was not checked; 96 is 100 % |
| `Steam's environment:` | `environment_lines`, `steam_environment` | `/proc/<pid>/environ` of `steam.sh` (what the session handed Steam), else of `steamrt64/steam` | what the game starts with besides its launch option |
| `This session's environment (Questlog's):` | `environment_lines` | this process's environment | what Questlog's launch inherits |

What cannot be read is a `note` with the reason, never a missing line:
no X11 display (run outside the desktop session), `xrandr` or `glxinfo`
not installed, `glxinfo` giving no renderer, `kscreen-doctor` giving no
outputs, a desktop other than KDE and GNOME for the scale.

Both environment lines list only variables named in `ENV_PREFIXES`
(`PROTON_`, `DXVK_`, `VKD3D_`, `WINE…`, `__GL_`, `MESA_`, `RADV_`,
`LD_PRELOAD`, …): those that change how Proton, Wine, DXVK or the driver
behave.

**Which Proton.** The `proton` script compares `config_info` with what it
would write on every start and rewrites it when they differ, so the file
belongs to the Proton that last ran the prefix. Its first line is only
the prefix's format version (`CURRENT_PREFIX_VERSION`, such as `11.0-100`,
which GE-Proton 11's builds share); the lines below are paths inside the
tool's folder as Steam's runtime container sees them (`/run/host/…` is the
host's `/…`). The build's name comes from that folder's `version` file
(`<time> <name>`): `cachyos-11.0-20261015-slr (folder proton-cachyos-slr)`.
A folder that is a link moved since to another build (`Proton-GE Latest`,
kept by tools that install GE-Proton) names the build it points at now.
Without a readable `version` file, the prefix version is shown and called
that.

Each check gives lines of `ok`, `note` or `PROBLEM`; the exit code is 1
when there is a problem. A check that raises is reported as a problem
itself instead of hiding the checks after it.

**`--report`.** Writes `~/a2qlinux-report-<date>-<time>.txt`: the
diagnosis, the last `REPORT_LOG_LINES` (400) lines of `launcher.log`, the
last 10 of `steam_launch.log`, `questlog.log` (`questlog_log_excerpt`:
whole up to `QUESTLOG_LOG_HEAD` + `QUESTLOG_LOG_TAIL` lines, 400 + 800,
else its start, where DXVK names its device and Chromium starts its GPU
process, and its end, the gap marked) and `questlog.log.1`, the run
before (200 + 400 lines), all passed through `Anonymiser`. That replaces
the home folder with `~`, the user name as a path component with `<user>`
(also between backslashes, as in Wine's `Z:\home\<user>\…`, which
`questlog.log` is full of), Steam account folders with
`userdata/<steam-id-N>`, the host name with `<host>`, and IPv4/IPv6
addresses with `<private-N>` (RFC 1918, 100.64.0.0/10, link-local),
`<public-N>` or `<ipv6-N>`; loopback and `0.0.0.0` stay. The same value always gets the same name, so "the game uses
`<private-2>`" still matches the interface line that captured on
`<private-2>`. The report is printed in full, and only then does it ask,
default no, whether to open a new GitHub issue. On yes, `xdg-open` opens
`github.com/raman78/A2Qlinux/issues/new` with a title and a body: a place
to say what happened, the request to attach the report file, the diagnosis,
and as many of the log's last lines as fit. The user logs in with their own
account, can change everything, and submits. A2Qlinux holds no token and
sends nothing itself; the issue is public, which is why the anonymising
happens before the file is written. Without a terminal to ask in, it only
says where the file is and where to file it.

The body is limited by the length of the URL: measured on 10 November 2026
without being logged in, GitHub took 6500 characters (redirecting to its
login page, which carries the whole URL along) and answered 7000 with an
error 500. `ISSUE_URL_LIMIT` is 6000; the full log is in the attached file.
If even the diagnosis does not fit, it is cut with a line saying so.

## 10. What Questlog updates can break

A2Qlinux depends on these properties of Questlog. `compatibility_problems`
in `a2qlinux/update.py` checks all of them except the link types before an
automatic update
(§6.6); for a manual update, check them by hand (`docs/UPDATING.md`,
"Updating by hand"):

| Property | Used by | How to check |
|---|---|---|
| the eleven pcap calls in §4.1 | `bridge/wpcap_bridge.c` | `grep -ohE 'pcap_[a-z_]+\(' …/workers/aion-2/*.cjs \| sort -u` in the unpacked `app.asar` |
| the capture device is picked by the game connection's address, listing anew per connection | §4.3 | `grep -c 'addresses.includes(' …/workers/aion-2/combat.cjs` |
| link types decoded: 1, 0, 108, 12, 101 (`QUESTLOG_LINKTYPES`) | §4.3 | by hand only: in `combat.cjs`, the function that reads source and destination from a frame, given the frame and `linkType`; its comparisons name the accepted types |
| Electron 44.5.1 (`KNOWN_ELECTRON`): tray icon id 3, `WM_ENDSESSION` ending the process | `questlog_ctl.exe` | `grep -aoE 'Electron/[0-9.]+' Questlog.exe`; for another version read `notify_icon_host.cc` and `native_window_views_win.cc` |
| `second-instance` shows the window | §6.3 | `grep -oE 'on\("second-instance",[^)]*\)' main.cjs` |
| overlay windows non-activatable (`focusable: false`) | §6.1 | `grep -c 'focusable:!1' main.cjs` |
| `resources/icon.png` in `app.asar`: a white Q on a dark tile | `a2qlinux_icon` (§12) | rerun `a2qlinux-setup` and look at `~/.local/share/icons/a2qlinux.png` |

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
6. A VPN switching servers while the game runs, tried with the game
   (8 November 2026): the first try lost capture on `proton0`, because the
   interface was recreated between two scans, which led to §4.3 step 4. With
   that fix, the second try: `proton0` came back with a new index, capture
   restarted within a second, the game reconnected 2 s later from the same
   address and data flowed to Questlog again. Switching the VPN off froze
   the game, whose connection stayed on the vanished address (§4.3, step 8);
   Questlog following the game onto the network card once the game has
   reconnected has not been seen yet.

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

**Shown version.** People see the version in three places, all from
`a2qlinux.shown_version`: the first line of the status window
(`A2Qlinux <version>.`), `--version` on `a2qlinux`, `a2qlinux-run` and
`a2qlinux-setup` (`a2qlinux` answers it itself; passed on to the launcher
it would open a terminal window), and the tray icon (a greyed-out first
menu line, and the tooltip `A2Qlinux <version> — Questlog for AION 2`). The
point is reports: which A2Qlinux a problem happened on, and whether an
update actually took effect. An installed package shows
`a2qlinux.__version__`. An editable install from a git checkout
(`pipx install --editable .`) writes `_version.py` once, at install time,
and never again, so there the number would be weeks stale (measured
2026-11-10: `0.1.1.dev15` while the tree was 0.4.0 plus 2 commits). When the
folder above the package holds `.git`, `shown_version` therefore asks
`git describe --tags --dirty` instead and shows e.g.
`0.4.0-2-g2321dc5-dirty (source checkout)`. If git fails, it shows the
built number with `(source checkout; git describe failed: <reason>)`, so a
wrong number never looks like a right one. A tag created on GitHub by a
release is not in a local clone until it is fetched (a plain
`git fetch origin` brings it, as the commit it marks is on a fetched
branch); until then `git describe` names the tag before it. Step 8 of
`docs/RELEASE.md` fetches it right after each release.

**Name and icon.** The menu entry, the desktop shortcut, the tray icon's
application name and the notifications are called `A2Qlinux`
(`a2qlinux.APP_NAME`), with `GenericName=Questlog for AION 2` and
`Keywords=Questlog;AION;…` in the entry, so a menu search for "questlog"
still finds it. Until v0.5.0 they were called "Questlog (AION 2)" and
showed Questlog's icon unchanged; that made A2Qlinux look like Questlog
itself, and when hiding Questlog's own tray icon failed, two identical
icons stood side by side. The icon (`a2qlinux.ICON`,
`~/.local/share/icons/a2qlinux.png`) is still Questlog's
`resources/icon.png`, taken from the player's own installation, because
A2Qlinux does not ship Questlog's logo; `setup_desktop.a2qlinux_icon`
colours its white Q red (`ICON_COLOUR`). It treats every pixel as a mix of
the tile's colour (the darkest opaque pixel) and white, and gives the white
share to the red, so the tile stays and the Q's anti-aliased edges stay soft;
a first try that scaled the white by brightness alone left a dark fringe. Qt (`QImage`) does the
decoding and encoding, since PyQt6 is already a dependency for the tray.
The entry's file keeps its old name, `questlog-aion2.desktop`
(`ENTRY_ID`, also the tray's `setDesktopFileName`): a new file name would
leave the old entry beside the new one on every updated installation.
`refresh_entries`, run on each `a2qlinux` start, updates an entry that
already runs this installation key by key (`with_current_keys`: every key
of `desktop_entry` except `Exec`, so options added to `Exec` by hand stay),
makes the icon if `a2qlinux.png` is missing and then removes the uncoloured
`questlog-aion2.png` (`OLD_ICON`). If the icon cannot be made (no Questlog
yet), the start's log says so and the old icon stays.

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
user there. PyQt6 (`python-pyqt6`) is installed as well, so that
the icon tests run `setup_desktop.a2qlinux_icon` itself rather than being
skipped.

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
| `interface` | `""` (every interface) | — | launcher (`--interface`, repeatable): a name or a list of names limiting `Captures` (§4.3) |
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

Developed and played on the one setup named at the top of this document.
Questlog's full-screen overlays (Black Market Cards, Alt+E editing) show
above the full-screen game only on KDE Plasma 6, with the KDE overlays of
§6.8, which were tested on Plasma 6.8.2 (Wayland) only: the rule list
`Order` and the script API were checked on that version, and an earlier
Plasma 6 that reads another list would leave the rule unapplied, that is,
the overlays as before. On other desktops they stay behind the game and
nothing is guaranteed. What depends on the
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
