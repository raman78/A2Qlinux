# Updating Questlog

This guide explains how Questlog is kept up to date under A2Qlinux, and how to
update it by hand if you prefer.

**A2Qlinux updates Questlog for you.** Questlog's own updater downloads new
versions but cannot install them under Proton (its installer stops, as
described in [INSTALL.md](INSTALL.md), "Installing Questlog"), so A2Qlinux
switches it off and does the job itself, the way Questlog does on Windows:
download in the background, install at the next start.

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

To turn automatic updates off, set `auto_update = false` in the settings file
(see "Settings" in [USING.md](USING.md)); `update_check_hours` there sets how
often A2Qlinux checks. Then update by hand.

### Updating by hand

1. Do steps 1–4 of "Installing Questlog" in [INSTALL.md](INSTALL.md) for the
   new version.
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

## Updating A2Qlinux itself

A2Qlinux does not update itself. When a new release is out (the project's
GitHub page, Releases), download its `a2qlinux-<version>-py3-none-any.whl`
and replace the old one with it:

```
pipx uninstall a2qlinux && pipx install ./a2qlinux-<version>-py3-none-any.whl
```

Quit Questlog first. The menu entry, the Steam launch option and Questlog
itself stay as they are; only A2Qlinux's own files are replaced. Which
version you have: `pipx list`.
