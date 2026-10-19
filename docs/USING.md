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

**Together with the game, from Steam.** In Steam, open AION 2's Properties >
General > Launch Options and paste the line `a2qlinux-setup` printed. It
looks like this:

```
/home/<you>/.local/bin/a2qlinux-steam %command%
```

The full path matters: Steam does not look in `~/.local/bin` by itself.

From then on, Play starts Questlog first and the game a few seconds later,
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
| `interface` | `""` | network interface the game uses; empty: chosen automatically when there is only one |
| `after_game` | `"keep"` | after the game: `"keep"` keeps Questlog open, `"close"` closes it |
| `after_game_delay` | `15` | with `"close"`: seconds after the game before Questlog closes; at least 10.5, so that Questlog has saved |
| `auto_update` | `true` | update Questlog automatically ([UPDATING.md](UPDATING.md)) |
| `update_check_hours` | `6` | hours between checks for a new Questlog |

A mistake in the file (an unknown name, a wrong value, a missing quote) does
not stop A2Qlinux: that setting keeps its default, and the status window and
a notification say which line is wrong.

The same can be set for a single start with an option, which wins over the
file: `--close-with-game`, `--no-auto-update`, `--interface <name>`. Put it
after `a2qlinux` in the menu entry's command, or between `a2qlinux-steam` and
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
- If you restart Questlog during a play session, the **Tracker Map** overlay
  stays empty until you change zone. That is when Questlog learns where your
  character is.
- Questlog's alerts work in the overlay. Its desktop pop-up notifications do
  not work under Proton.
