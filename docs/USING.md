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

From then on, Play starts the game first and Questlog a moment later, once
the game runs. If Questlog is already open when you press Play, the game
joins it; nothing restarts.

Keep the status window open while you use Questlog. It carries the traffic
to Questlog, and it shows what A2Qlinux is doing. The line
`Game traffic is flowing to Questlog.` means everything is connected. The
window closes by itself when Questlog quits. If something fails, it stays
open with the message until you press Enter.

**When the game ends**, Questlog stays with you: look through your fights,
use the database or the map. It also waits for the game: start it again and
the traffic flows to Questlog again, whichever way you start it.

About 15 seconds after the game ends, Questlog briefly closes and comes back,
as it was: with its window open if it was open, otherwise only in the tray.
This is what lets Steam see the game as closed. Under Proton, Steam
counts the game as running for as long as anything else runs in the game's
Windows environment, and Questlog runs in it because that is the only way it
can see the game. Restarted, Questlog is in an environment of its own until
you press Play again.

If you would rather have Questlog close for good 15 seconds after the game,
put `--close-with-game` between `a2qlinux-steam` and `%command%` in Steam's
launch option.

Tip: to see A2Qlinux's messages in the terminal you are in, instead of a new
window, run `a2qlinux-run`.

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
