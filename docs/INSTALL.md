# Installing Questlog and A2Qlinux on Linux

This guide sets up Questlog Desktop, the Windows-only damage meter and overlay
app for AION 2, to run next to the game on Linux. At the end you will have a
"Questlog (AION 2)" entry in your applications menu. Daily use is in
[USING.md](USING.md); how it works inside is in
[ARCHITECTURE.md](ARCHITECTURE.md), which you do not need.

## The idea

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
| `python-pipx` | installs A2Qlinux in its own environment |
| `xdotool`, `libnotify`, `konsole` | window activation, notifications, the status window |
| `p7zip` | unpacking Questlog's installer, also for its updates |

The rest A2Qlinux needs (the tray icon library, among others) comes with it
when pipx installs it.

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

Tip: if you keep Questlog somewhere else, give the folder once as
`a2qlinux-setup --questlog-dir <folder>` (next section); it is written into
A2Qlinux's settings file.

## Installing A2Qlinux

A2Qlinux is installed with pipx, which keeps it and the libraries it uses in
a folder of their own and puts its commands in `~/.local/bin`.

1. Download the file `a2qlinux-<version>-py3-none-any.whl` from the newest
   release on the project's GitHub page (Releases).
2. Install it:
   ```
   pipx install ./a2qlinux-<version>-py3-none-any.whl
   ```
3. Create the menu entry (and, with `--desktop-shortcut`, a desktop icon):
   ```
   a2qlinux-setup --desktop-shortcut
   ```

`a2qlinux-setup` creates A2Qlinux's settings file (see "Settings" in
[USING.md](USING.md)) unless it exists, checks the packages from the list above
and names any that are missing. It takes Questlog's icon from your Questlog folder (A2Qlinux
does not ship Questlog's logo) and creates the "Questlog (AION 2)" entry. At
the end it prints the line for Steam's launch options (see
[USING.md](USING.md)) and either "Ready" or a list of what is still missing.
It installs no packages and changes nothing in the game.

The entry keeps itself up to date: each time `a2qlinux` starts, it checks
that the menu entry (and the desktop icon, if you have one) still runs this
installation, and writes it again if not, for example after A2Qlinux was
reinstalled elsewhere. Options you added to the entry by hand stay.

Tip: if `a2qlinux-setup` is not found, run `pipx ensurepath` once and open a
new terminal.

**From the source code instead** (for changing A2Qlinux itself): in a copy of
the repository, build the small Windows parts once (needs `clang`, `lld` and
`wine`), then install that copy so that your changes take effect at once:
```
bash bridge/build.sh && pipx install --editable .
```
Then run `a2qlinux-setup` as above.

Next: [USING.md](USING.md).

## Removing A2Qlinux

1. Quit Questlog from the tray icon.
2. Clear AION 2's launch options in Steam.
3. Uninstall A2Qlinux:
   ```
   pipx uninstall a2qlinux
   ```
4. Delete the menu entry, the desktop shortcut and the icon:
   ```
   rm ~/.local/share/applications/questlog-aion2.desktop ~/Desktop/questlog-aion2.desktop ~/.local/share/icons/questlog-aion2.png
   ```
5. Delete A2Qlinux's capture library from the game's Proton environment, the
   folder `drive_c/windows/system32/Npcap` inside
   `steamapps/compatdata/3393110/pfx` in your Steam library.
6. If you no longer want Questlog either, delete `~/Games/Questlog` and the
   previous version A2Qlinux kept next to it after an update (for example
   `~/Games/Questlog-0.1.34`). Questlog's fights and settings live in the
   game's Proton environment under
   `drive_c/users/steamuser/AppData/Roaming/Questlog`.
