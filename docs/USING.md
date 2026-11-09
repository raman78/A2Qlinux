# Using Questlog with A2Qlinux

This guide covers starting Questlog, its tray icon and playing with it, once
it is installed ([INSTALL.md](INSTALL.md)). Updates are in
[UPDATING.md](UPDATING.md), problems in [TROUBLESHOOTING.md](TROUBLESHOOTING.md).

## Starting Questlog

There are two ways, and you can use both.

**From the menu or desktop icon.** "Questlog (AION 2)" opens a small terminal
window, A2Qlinux's status window, and then Questlog. This works with or
without the game: without it, you can look through saved fights, the
database and the map. When you start the game later, Questlog picks up the
traffic by itself. Your character appears in Questlog after you log in or
change zone.

**Together with the game, from Steam.** Once AION 2 has the Steam launch
option (set it up as in
[INSTALL.md](INSTALL.md#starting-questlog-with-the-game-from-steam-optional)),
Play starts Questlog first and the game a few seconds later,
once Questlog runs. If Questlog is already open when you press Play, the game
starts at once and joins it; nothing restarts.

Keep the status window open while you use Questlog. It carries the traffic
to Questlog, and it shows what A2Qlinux is doing. The line
`Game traffic is flowing to Questlog.` means everything is connected. The
window closes by itself when Questlog quits. If something fails, it stays
open with the message until you press Enter.

**When the game ends**, Questlog stays with you: look through your fights,
use the database or the map. It also waits for the game: start it again and
the traffic flows to Questlog again, whichever way you start it.

A moment after the game ends, Steam shows it as closed again, and Questlog
is not touched. Under Proton, a small helper that starts the game waits for
everything else in the game's Windows environment to end, Questlog included,
and Steam counts the game as running until then. A2Qlinux ends that helper
once the game has gone, the same way Steam's own Stop button does.

One case still needs Questlog to restart: when the game was started before
Questlog (Play without the launch option above). Then the game's start owns
the Windows environment Questlog runs in. About 10 seconds after the game
ends, once Questlog has saved the last fight, Questlog briefly closes and
comes back as it was: with its window open if it was open, otherwise only in
the tray. After that, the next game joins Questlog again and nothing
restarts.

If you would rather have Questlog close for good after the game, set
`after_game = "close"` in the settings file (next section).

Tip: to see A2Qlinux's messages in the terminal you are in, instead of a new
window, run `a2qlinux-run`.

## Settings

A2Qlinux reads its settings from `~/.config/a2qlinux/config.toml`, a text
file `a2qlinux-setup` creates with every setting at its default and a line
explaining each. Change a value, save, and start Questlog again; settings
are read when A2Qlinux starts.

| Setting | Default | What it does |
|---|---|---|
| `questlog_dir` | `"~/Games/Questlog"` | folder with Questlog |
| `interface` | `""` | network interfaces to listen on: a name such as `"eth0"`, or a list such as `["eth0", "wg0"]`; empty: all of them, and Questlog follows the game on whichever it uses |
| `after_game` | `"keep"` | after the game: `"keep"` keeps Questlog open, `"close"` closes it |
| `after_game_delay` | `15` | with `"close"`: seconds after the game before Questlog closes; at least 10.5, so that Questlog has saved |
| `auto_update` | `true` | update Questlog automatically ([UPDATING.md](UPDATING.md)) |
| `update_check_hours` | `6` | hours between checks for a new Questlog |

A mistake in the file (an unknown name, a wrong value, a missing quote) does
not stop A2Qlinux: that setting keeps its default, and the status window and
a notification say which line is wrong.

The same can be set for a single start with an option, which wins over the
file: `--close-with-game`, `--no-auto-update`, `--interface <name>` (once
per interface). Put it
after `a2qlinux` in the menu entry's command, or between `a2qlinux-steam` and
`%command%` in Steam's launch option.

## A VPN or several network connections

You do not need to set anything for a VPN, Wi-Fi next to a cable, or any
other mix of network connections.

**How it works.** Every network connection of your computer has its own
address. When a VPN is on, the game talks to its server from the VPN's
address, and the cable or Wi-Fi only carries an encrypted copy that
Questlog cannot read. So A2Qlinux does not try to guess the right
connection in advance. It listens on all of them at once, and Questlog
looks at the address the game is actually using and reads the connection
that has it, the same way it does on Windows.

Because of that:

- Switching the VPN on or off, or to another server, needs no restart of
  Questlog. A2Qlinux notices the change within a few seconds, and Questlog
  moves over once the game has reconnected through the new connection.
- Changing VPN servers keeps your VPN address, and the game reconnects in a
  moment. Switching the VPN **off** while playing is different: the address
  the game was talking from disappears, and the game freezes until it gives
  up and reconnects, which can take a while. That happens with or without
  A2Qlinux; the status window says "AION 2's connection … still uses …,
  which no network interface has any more". Switch the VPN off between
  play sessions instead.
- Right after the switch, Questlog may show "Npcap lists no adapter with
  this address" for a few seconds. It goes away on its own.
- Listening on a connection the game does not use costs nothing: nothing
  of the game passes there, so nothing is read.

It does not matter which VPN you use. Each VPN program names its
connection in its own way: `wg0` for WireGuard, `tun0` for many OpenVPN
setups, `proton0` for Proton VPN, `tailscale0` for Tailscale, and so on.
A2Qlinux does not look at the name; it listens on every connection that has
an address, whatever it is called.

**What you see.** The status window lists every connection it listens on,
then says which one Questlog follows once the game is connected. With a
VPN on it looks like this, for example (your names and addresses differ):

```
[a2qlinux] Capturing on eth0 (192.168.1.20), TCP port 13328.
[a2qlinux] Capturing on wg0 (10.2.0.2), TCP port 13328.
[a2qlinux] Questlog follows the game's connection on wg0 (10.2.0.2).
[a2qlinux] Game traffic is flowing to Questlog.
```

The first line, for the cable, is normal: A2Qlinux listens there too, in
case the VPN is switched off.

**Leaving connections out.** Set `interface` in the settings file only if
you want A2Qlinux to stay off some connections. This command lists your
connections by name, with their addresses:

```
ip -brief address
```

Put the names you want in a list, for example
`interface = ["eth0", "wg0"]`, using the names the command shows on your
computer. If the game later runs through a
connection you left out, the status window and a notification say so.

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
| **Quit Questlog** | the icon and window disappear at once; Questlog ends within about a second, or, while the game is running, up to 10 seconds later once it has saved; the status window then closes |
| start "Questlog (AION 2)" while Questlog runs | Questlog's window opens; no second copy starts |

**Why quitting can take 10 seconds.** Questlog writes what it learns from the
game to disk within 10 seconds, and the only way to end it from outside under
Proton skips its last save. So A2Qlinux waits until 10 seconds have passed
since the last game data reached Questlog. Without the game (or a while after
closing it) that is already the case and Questlog ends at once; while you
play, it is hidden first and ended when the 10 seconds are up. The game is
not touched.

**Changed your mind?** If you start "Questlog (AION 2)" from the menu during
that wait, or press Play in Steam, the quit is called off: the icon
comes back and Questlog keeps running. If it had already ended, a fresh
Questlog starts.

## Using Questlog while you play

- Overlays (the meter, alerts, the tracker map) appear over the game and let
  clicks pass through to it, as on Windows.
- With Questlog's full window open behind the game, clicks in the game stay
  in the game. To work in Questlog's window, switch to it with Alt+Tab, the
  taskbar or the tray icon.
- You can quit Questlog during play and start it again from the menu; the
  game keeps running. After such a restart the **Tracker Map** overlay stays
  empty, and the meter shows no fights, until you change zone. That is when
  Questlog learns who and where your character is.
- Questlog's alerts work in the overlay. Its desktop pop-up notifications do
  not work under Proton.
- **Black Market Cards** needs a step of its own; see the next section.

### Black Market Cards

Black Market Cards is the Questlog overlay that writes its notes straight
onto the cards of the in-game Black Market shop: your pet's level and souls,
what an item unlocks or completes, the deals worth taking and how rare an
item is. It appears when you open a shop tab, while the game's mouse cursor
is visible. Once the cursor goes away, back in the game world, the notes
hide until you open a tab again.

**Why it needs extra help on Linux.** Most of Questlog's overlays (the
meter, alerts, the Black Market list) are small windows, and they always
stay above the game. The cards are drawn in one transparent window that
covers the whole screen, together with the small overlay-controls icon.
Your desktop treats a window of that size like an ordinary program window
and keeps the full-screen game above it, so without help you never see the
cards. On KDE Plasma 6, A2Qlinux can add a KDE window rule for that one
window, the "KDE overlays". The window then shows above AION 2 while the
game is the window in front, and turns invisible when you switch to another
program, so the notes never hang over your other windows.

| Your desktop | Black Market Cards |
|---|---|
| KDE Plasma 6, KDE overlays set up | shown over the shop while the game is in front |
| KDE Plasma 6, KDE overlays not set up | hidden behind the game |
| any other desktop | hidden behind the game; nothing is changed there |

To use the cards:

1. In Questlog's overlay list, turn on **Black Market Cards**. If you had
   saved your overlay list before this overlay existed, it is off: Questlog
   does not add new overlays to a list you saved.
2. On KDE Plasma 6, run `a2qlinux-setup` and answer the question about the
   KDE overlays with Enter (yes). If you said no earlier, this sets them up
   without asking:
   ```
   a2qlinux-setup --kde-overlays
   ```
3. In the overlay's options, set **UI scale size** to the size of the
   game's interface: 1 = 75 %, 2 = 80 %, 3 = 85 %, 4 = 90 %, 5 = 100 %.
   Questlog places the notes where the cards are at that size, so with the
   wrong value they land beside the cards.
4. Open a tab in the Black Market. The notes appear on the cards.

To remove the KDE overlays again, run `a2qlinux-setup --no-kde-overlays`.
It takes out exactly what was added and leaves the rest of your KDE
settings as they were.
