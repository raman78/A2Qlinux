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
for Npcap's library. Questlog's program is not changed: it runs as on
Windows, inside the same Proton environment as the game, and sees the game
the way it expects to. The one file A2Qlinux removes from Questlog's folder
is the setting of Questlog's own updater, because that updater cannot
install under Proton; A2Qlinux updates Questlog instead
([UPDATING.md](UPDATING.md)).

Because Questlog and the game then share one Windows environment, A2Qlinux
also takes care of a few things around them. It starts the two in the right
order. It keeps your clicks in the game when Questlog's window is open behind
it. And it shows its own tray icon in place of Questlog's, whose menu does not
work reliably under Proton.

## The steps at a glance

| Step | What you do | Takes |
|---|---|---|
| 1 | [Check what you need](#what-you-need-before-you-start) | a minute |
| 2 | [Install the packages](#installing-the-packages) | one command |
| 3 | [Allow capturing without administrator rights](#allowing-capture) | one or two commands, then log in again |
| 4 | [Install Questlog](#installing-questlog) | four commands |
| 5 | [Install A2Qlinux](#installing-a2qlinux) | two commands |
| 6 | [Check that it works](#checking-that-it-works) | a game session |
| 7 | [Start Questlog with the game from Steam](#starting-questlog-with-the-game-from-steam-optional) | optional |

The commands below are typed in a terminal (Konsole, GNOME Terminal, or
whatever your desktop has). Copy each one whole; most are a single long
line.

## What you need before you start

- **AION 2 from Steam, started at least once**, so that its Proton
  environment (the "prefix", the folder where a Windows game keeps its
  Windows files) exists. Set the game to **borderless window** mode, or
  Questlog's overlays end up under it.
- **Steam from your distribution's packages or from Valve's website.**
  Steam installed from Flatpak does not work: it runs in a sandbox that
  cannot see A2Qlinux, so its launch option cannot start it. Steam from
  Snap is sandboxed in the same way and has not been tried.
- **A desktop with a system tray**, where A2Qlinux shows its Questlog icon.
  KDE Plasma, Xfce, Cinnamon and MATE have one. GNOME needs the extension
  "AppIndicator and KStatusNotifierItem Support"; Ubuntu ships it already
  switched on. A2Qlinux checks the tray for you in step 5. It is used
  daily on KDE Plasma 6 (Wayland); other desktops have not been played on
  yet.
- **Python 3.11 or newer.** `python3 --version` tells you yours. Ubuntu
  22.04 has 3.10 and is too old; Ubuntu 24.04, Debian 12 and newer, Fedora,
  openSUSE Tumbleweed and Arch are fine.
- **systemd**, which almost every distribution uses. Without it the menu
  entry works, but the Steam launch option cannot start Questlog.

## Installing the packages

Install these with your distribution's package manager. Use the command for
your distribution:

| Distribution | Command |
|---|---|
| Arch, CachyOS | `sudo pacman -S --needed wireshark-cli protontricks python-pipx 7zip xdotool libnotify xcb-util-cursor` |
| Ubuntu | `sudo add-apt-repository multiverse && sudo apt install wireshark-common protontricks pipx p7zip-full xdotool libnotify-bin libxcb-cursor0` |
| Debian 12 | `sudo apt install wireshark-common protontricks pipx p7zip-full xdotool libnotify-bin libxcb-cursor0` |
| Debian 13 | `sudo apt install wireshark-common pipx p7zip-full xdotool libnotify-bin libxcb-cursor0 && pipx install protontricks` |
| Fedora | `sudo dnf install wireshark-cli protontricks pipx 7zip xdotool libnotify xcb-util-cursor` |
| openSUSE Tumbleweed | `sudo zypper install wireshark protontricks python313-pipx 7zip xdotool libnotify-tools libxcb-cursor0` |

On Debian and Ubuntu, installing `wireshark-common` asks "Should
non-superusers be able to capture packets?". Answer **Yes**; step 3 explains
why. If you answered No, step 3 shows how to change it.

What each package is for:

| Package | What it is for |
|---|---|
| Wireshark's command-line part | captures the game's traffic (`dumpcap`) |
| protontricks | starts Questlog inside the game's Proton environment |
| pipx | installs A2Qlinux in a folder of its own |
| 7zip / p7zip | unpacks Questlog's installer, now and for its updates |
| xdotool | brings Questlog's window to the front |
| libnotify | desktop notifications |
| xcb-cursor | the tray icon in an X11 session (a Wayland session does not need it) |

Notes:

- **Ubuntu** keeps protontricks in the `multiverse` section, which the
  command above switches on. **Debian 13** has no protontricks package, so
  the command installs it with pipx; that gives the `protontricks-launch`
  command A2Qlinux uses. Do not use protontricks from Flatpak: A2Qlinux
  needs the command in your normal system.
- **openSUSE** names pipx after the Python version: `python313-pipx` is for
  Python 3.13; pick the one matching `python3 --version`.
- A2Qlinux's status window opens in a terminal: the first it finds of
  Konsole, GNOME Terminal, Ptyxis, the Xfce and MATE terminals, Debian's
  default terminal and `xterm`. Every desktop named above comes with one.
- The rest A2Qlinux needs (the tray icon library, among others) comes with
  it in step 5.

## Allowing capture

A2Qlinux reads the game's traffic with Wireshark's capture tool, `dumpcap`.
Capturing network traffic normally needs administrator rights. The
distributions solve this with a group called `wireshark`: its members may
run `dumpcap`, and nothing else gets those rights. So you add yourself to
that group once, and A2Qlinux never needs `sudo`.

1. **Debian and Ubuntu only:** make sure capturing is allowed for the
   group. If you answered Yes during step 2, skip this. Otherwise run this
   and choose **Yes**:
   ```
   sudo dpkg-reconfigure wireshark-common
   ```
2. Add yourself to the group:
   ```
   sudo usermod -aG wireshark $USER
   ```
3. Log out of your desktop and log in again. Group membership is read at
   login, so until then nothing changes.
4. Check it. This lists your network devices; an error about permissions
   means one of the steps above is missing:
   ```
   dumpcap -D
   ```

## Installing Questlog

Questlog's own installer stops under Proton without installing anything.
So Questlog is installed by unpacking its files into a folder, by default
`~/Games/Questlog`. The commands always fetch the newest version; there is
nothing to change in them.

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

Do **not** install Npcap itself into the game's Proton environment. It is a
Windows driver and does not work there. A2Qlinux provides what Questlog needs
instead.

Tip: if you keep Questlog somewhere else, give the folder once as
`a2qlinux-setup --questlog-dir <folder>` (next section); it is written into
A2Qlinux's settings file.

## Installing A2Qlinux

A2Qlinux is installed with pipx, which downloads it from PyPI (the Python
package index), keeps it and the libraries it uses in a folder of their own
and puts its commands in `~/.local/bin`. The package already contains the
small Windows parts A2Qlinux puts into the game's Proton environment, so
nothing has to be built.

1. Install it:
   ```
   pipx install a2qlinux
   ```
2. Let pipx add `~/.local/bin` to your command path, then **close the
   terminal and open a new one**, so that the new commands are found:
   ```
   pipx ensurepath
   ```
3. Create the menu entry (and, with `--desktop-shortcut`, a desktop icon).
   Run it on your desktop, not over SSH:
   ```
   a2qlinux-setup --desktop-shortcut
   ```
4. Read the end of what it printed. "Ready" means you can go on. Otherwise
   it lists what is still missing, each with what to do; fix those and run
   step 3 again.

What `a2qlinux-setup` does: it creates A2Qlinux's settings file (see
"Settings" in [USING.md](USING.md)) unless it exists, and checks the
packages from step 2 and your membership of the `wireshark` group. It starts
A2Qlinux's tray icon for a moment, without showing it, to see that it can
run on your desktop; that is why it has to run on the desktop. If the icon
cannot run, it prints why (see "The tray icon" in
[TROUBLESHOOTING.md](TROUBLESHOOTING.md)). It takes Questlog's icon from
your Questlog folder (A2Qlinux does not ship Questlog's logo), creates the
"Questlog (AION 2)" entry, and prints the line for Steam's launch options,
used in the optional last step. It installs no packages and changes nothing
in the game.

The entry keeps itself up to date: each time `a2qlinux` starts, it checks
that the menu entry (and the desktop icon, if you have one) still runs this
installation, and writes it again if not, for example after A2Qlinux was
reinstalled elsewhere. Options you added to the entry by hand stay.

**From the source code instead** (for changing A2Qlinux itself): in a copy of
the repository, build the small Windows parts once (needs `clang`, `lld` and
`wine`), then install that copy so that your changes take effect at once:
```
bash bridge/build.sh && pipx install --editable .
```
Then run `a2qlinux-setup` as above. The build script looks for Wine's
files where Arch and CachyOS put them (`/usr/include/wine`,
`/usr/lib/wine/x86_64-windows`). On other distributions `pipx install
a2qlinux` is the simpler way, since that package comes with these parts
built.

## Checking that it works

1. Start **Questlog (AION 2)** from your applications menu. A small
   terminal window opens, A2Qlinux's status window, and then Questlog.
   Keep the status window open while you use Questlog; it carries the game
   traffic to Questlog.
2. Look at the system tray: one Questlog icon, A2Qlinux's. Right-click it
   to see Open Questlog and Quit Questlog.
3. Start AION 2 from Steam and log in to a character.
4. The status window says `Game traffic is flowing to Questlog.` and
   Questlog shows your character. Fight something: the damage meter fills.

If something differs, the status window says what went wrong;
[TROUBLESHOOTING.md](TROUBLESHOOTING.md) lists the messages and what to do.

## Starting Questlog with the game from Steam (optional)

You can start Questlog from the menu entry and play next to it. If you
would rather have it come up by itself whenever you start AION 2, give
Steam a launch option (a command Steam runs in place of the game, which then
starts the game itself). With it, Play starts Questlog first and the game a
few seconds later, inside the Windows environment Questlog already runs in.
That order matters: started this way, the game cannot wait on Questlog, and
Steam sees the game as closed as soon as you leave it, while Questlog stays
open. Why this is so is in [USING.md](USING.md).

1. Find the line to paste. `a2qlinux-setup` printed it at the end, under
   "Steam > AION 2 > Properties > General > Launch Options". It looks like
   this, with your user name:
   ```
   /home/<you>/.local/bin/a2qlinux-steam %command%
   ```
   If you no longer have it, `command -v a2qlinux-steam` prints the first
   part; add ` %command%` after it.
2. In Steam's Library, right-click **AION 2** and choose **Properties…**.
3. On the **General** page, find the **Launch Options** field at the bottom.
4. Paste the line into the field and close the window.

Keep the full path. Steam does not look in `~/.local/bin` by itself, so a
bare `a2qlinux-steam %command%` is not found. `%command%` stands for the
game's own start command, and Steam fills it in; leave it as it is.

```
┌─ AION 2 — Properties ───────────────────────────────────────────┐
│  General      │  ...                                            │
│  Compatibility│                                                 │
│  ...          │  LAUNCH OPTIONS                                 │
│               │  ┌───────────────────────────────────────────┐  │
│               │  │/home/<you>/.local/bin/a2qlinux-steam %comm│  │
│               │  └───────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────┘
```

To check it, press **Play**. First A2Qlinux's status window and Questlog
appear, then, a few seconds later, the game. If Questlog was already open,
the game starts at once and Questlog stays as it was.

To stop starting Questlog with the game, empty the Launch Options field
again. The menu entry keeps working either way.

Next: [USING.md](USING.md).

## Removing A2Qlinux

1. Quit Questlog from the tray icon.
2. Clear AION 2's launch options in Steam.
3. Uninstall A2Qlinux:
   ```
   pipx uninstall a2qlinux
   ```
4. Delete the menu entry, the icon and the settings file:
   ```
   rm -r ~/.local/share/applications/questlog-aion2.desktop ~/.local/share/icons/questlog-aion2.png ~/.config/a2qlinux
   ```
   If you made a desktop shortcut, delete `questlog-aion2.desktop` from
   your desktop too.
5. Delete A2Qlinux's capture library from the game's Proton environment, the
   folder `drive_c/windows/system32/Npcap` inside
   `steamapps/compatdata/3393110/pfx` in your Steam library.
6. If you no longer want Questlog either, delete `~/Games/Questlog` and the
   previous version A2Qlinux kept next to it after an update (for example
   `~/Games/Questlog-0.1.34`). Questlog's fights and settings live in the
   game's Proton environment under
   `drive_c/users/steamuser/AppData/Roaming/Questlog`.
