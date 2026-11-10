# Updating Questlog

This guide explains how Questlog is kept up to date under A2Qlinux, and how to
update it by hand if you prefer.

**A2Qlinux updates Questlog for you.** Questlog's own updater downloads new
versions but cannot install them under Proton (its installer stops without
installing anything), so A2Qlinux
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

### Installing Questlog by hand

`a2qlinux-setup` installs Questlog for you ([INSTALL.md](INSTALL.md#installing-a2qlinux-and-questlog)).
These commands do the same by hand, for when that fails, or when you want
to see each step. They always fetch the newest version; there is nothing to
change in them.

1. Download the newest installer, and the small file `latest.yml` that
   names it and holds its checksum:
   ```
   mkdir -p /tmp/qlupd/dl && cd /tmp/qlupd/dl && curl -s -o latest.yml https://cdn.questlog.gg/desktop/latest.yml && curl -LO "https://cdn.questlog.gg/desktop/$(sed -n 's/^path: //p' latest.yml)"
   ```
2. Check that the download is complete and genuine. This prints `OK` and
   the file name; if it prints `MISMATCH`, run step 1 again:
   ```
   python3 -c "import re,hashlib,base64,pathlib;y=pathlib.Path('latest.yml').read_text();f=re.search(r'^path: (.+)',y,re.M)[1];s=re.search(r'^sha512: (.+)',y,re.M)[1];print('OK' if base64.b64encode(hashlib.sha512(pathlib.Path(f).read_bytes()).digest()).decode()==s else 'MISMATCH',f)"
   ```
3. Unpack the installer, then the program package inside it:
   ```
   mkdir -p /tmp/qlupd/nsis /tmp/qlupd/app && cd /tmp/qlupd/nsis && 7z x ../dl/questlog-setup-*.exe && cd /tmp/qlupd/app && 7z x '/tmp/qlupd/nsis/$PLUGINSDIR/app-64.7z'
   ```
4. Move the program into place and delete the temporary files:
   ```
   mkdir -p ~/Games/Questlog && cp -a /tmp/qlupd/app/. ~/Games/Questlog/ && cd ~ && rm -rf /tmp/qlupd
   ```
5. Run `a2qlinux-setup` (it now finds Questlog and installs nothing).

Do not install Npcap itself into the game's Proton environment. It is a
Windows driver and does not work there; A2Qlinux replaces it.

### Updating by hand

1. Do steps 1–3 of "Installing Questlog by hand" above. They fetch the
   newest version; do not do step 4, which would copy it over the current
   folder.
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

A2Qlinux does not update itself; pipx does it when you ask. What changed
in each version is in the project's changelog (`CHANGELOG.md` on its GitHub
page). Quit Questlog first, then:

```
pipx upgrade a2qlinux
```

pipx fetches the newest version from PyPI and replaces A2Qlinux's own files.
The menu entry, the Steam launch option, your settings file and Questlog
itself stay as they are: they point at the `a2qlinux` commands in
`~/.local/bin`, which keep their names. Which version you have:
`a2qlinux --version`, or the first line of the tray icon's menu once
Questlog runs again (if that still shows the old number, Questlog was not
quit before the upgrade: quit it and start it again).

If you installed A2Qlinux from a downloaded `.whl` file before it was on
PyPI, pipx keeps using that file: `pipx upgrade` says A2Qlinux "is
unchanged … because it is installed from the local source". Switch over
once with `pipx uninstall a2qlinux && pipx install a2qlinux`; nothing else
changes, and from then on `pipx upgrade a2qlinux` works.
