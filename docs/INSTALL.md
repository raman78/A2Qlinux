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
| 4 | [Install A2Qlinux, which installs Questlog](#installing-a2qlinux-and-questlog) | three commands |
| 5 | [Check that it works](#checking-that-it-works) | a game session |
| 6 | [Start Questlog with the game from Steam](#starting-questlog-with-the-game-from-steam-optional) | optional |

You do not have to get steps 2 and 3 exactly right the first time. In step
4, `a2qlinux-setup` checks everything A2Qlinux needs, and for anything
missing it prints the exact command to run on your distribution.

The commands below are typed in a terminal (Konsole, GNOME Terminal, or
whatever your desktop has). Copy each one whole.

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
  switched on. `a2qlinux-setup` checks the tray for you. It is used
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
non-superusers be able to capture packets?". Answer **Yes**; "Allowing
capture" below explains why. If you answered No, it shows how to change it.

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
  A2Qlinux itself.

## Allowing capture

A2Qlinux reads the game's traffic with Wireshark's capture tool, `dumpcap`.
Capturing network traffic normally needs administrator rights. The
distributions solve this with a group called `wireshark`: its members may
run `dumpcap`, and nothing else gets those rights. So you add yourself to
that group once, and A2Qlinux never needs `sudo`.

1. **Debian and Ubuntu only:** make sure capturing is allowed for the
   group. If you answered Yes while installing the packages, skip this.
   Otherwise run this and choose **Yes**:
   ```
   sudo dpkg-reconfigure wireshark-common
   ```
2. Add yourself to the group:
   ```
   sudo usermod -aG wireshark $USER
   ```
3. Log out of your desktop and log in again. Group membership is read at
   login, so until then nothing changes.
4. `a2qlinux-setup` (next section) checks the result: it captures for one
   second, the real test. If capturing is still not allowed, it says which
   of the commands above is missing on your system.

## Installing A2Qlinux and Questlog

A2Qlinux is installed with pipx, which downloads it from PyPI (the Python
package index), keeps it and the libraries it uses in a folder of their own
and puts its commands in `~/.local/bin`. The package already contains the
small Windows parts A2Qlinux puts into the game's Proton environment, so
nothing has to be built.

Questlog is not installed with its own installer: under Proton that stops
without installing anything. A2Qlinux installs Questlog itself, the same way
it later keeps Questlog up to date: it downloads the newest version from
Questlog's authors, checks that the download is complete and genuine,
unpacks it, checks that this version works with A2Qlinux, and puts it in
`~/Games/Questlog`. It does not install Npcap, the Windows capture driver
Questlog normally asks for; it does not work under Proton, and A2Qlinux
replaces it.

1. Install A2Qlinux:
   ```
   pipx install a2qlinux
   ```
2. Let pipx add `~/.local/bin` to your command path, then **close the
   terminal and open a new one**, so that the new commands are found:
   ```
   pipx ensurepath
   ```
3. Run the setup on your desktop, not over SSH (`--desktop-shortcut` also
   puts an icon on the desktop):
   ```
   a2qlinux-setup --desktop-shortcut
   ```
4. Read the end of what it printed:
   - **"Ready"**: go on to the next section.
   - **"Not ready yet"**: a list of what is missing, each with the command
     to run, for example `sudo apt install xdotool`. Run those commands,
     log out and in again if the list says so, then run `a2qlinux-setup`
     again.
     Nothing is done twice: what is already in place is only checked.

What the setup does, in order:

| It… | What you see |
|---|---|
| creates A2Qlinux's settings file, unless it exists (see "Settings" in [USING.md](USING.md)) | `Settings: …` |
| checks the programs from "Installing the packages", and for missing ones prints one install command for your distribution | `missing: …` and the command |
| tries a one-second capture, to see that capturing is allowed | `capturing is not allowed yet …` and the commands, if not |
| starts A2Qlinux's tray icon for a moment, without showing it, to see that it can run on your desktop | a reason, if not; see "The tray icon" in [TROUBLESHOOTING.md](TROUBLESHOOTING.md) |
| installs Questlog in its folder (`~/Games/Questlog`, or the one given with `--questlog-dir`) if it is not there yet (about 130 MB) | `Downloading Questlog …`, then `Installed Questlog …` |
| takes Questlog's icon from it (A2Qlinux does not ship Questlog's logo) | `Icon: …` |
| creates the "Questlog (AION 2)" entry in your applications menu | `Menu entry: …` |
| on KDE Plasma 6 only: explains the KDE overlays, which let Questlog's Black Market Cards show above the game, and asks whether to set them up (Enter means yes) | the explanation, `Set this up now? [Y/n]`, then `KDE: window rule … are in place.` |
| checks Steam's launch option for AION 2, used in the optional last section: says when it is set, otherwise prints the line to paste | `Steam launch option: set (…)`, or `Steam > AION 2 > …` and the line |

It runs nothing with `sudo` and changes nothing in the game; the commands
that need administrator rights are printed for you to run.

**Questlog in another folder.** A2Qlinux keeps Questlog in `~/Games/Questlog`
unless you tell it otherwise. To use another folder, run the setup once
with it:

```
a2qlinux-setup --questlog-dir <folder>
```

The setup writes that folder into A2Qlinux's settings file (only that line;
your other settings stay), so the menu entry, the Steam launch option and
every later run of the setup use it; you do not give it again. Then:

| What is in the folder | What the setup does |
|---|---|
| a Questlog you unpacked before (`Questlog.exe` is there) | uses it; nothing is downloaded |
| nothing, or the folder does not exist yet | installs the newest Questlog there |
| other files, but no `Questlog.exe` | installs nothing, and says so; choose an empty folder |

To move back to the default, run it with `--questlog-dir ~/Games/Questlog`,
or change `questlog_dir` in the settings file.

If the automatic installation fails, the message says why; installing
Questlog by hand is described in
[UPDATING.md](UPDATING.md#installing-questlog-by-hand).

The menu entry keeps itself up to date: each time `a2qlinux` starts, it
checks that the entry (and the desktop icon, if you have one) still runs
this installation, and writes it again if not, for example after A2Qlinux
was reinstalled elsewhere. Options you added to the entry by hand stay.

### From the source code instead

This is for changing A2Qlinux itself; to use it, the PyPI package above is
all you need. Installing from a copy of the repository differs in two
ways. The small Windows parts A2Qlinux puts into the game's Proton
environment are not in the repository, only in the PyPI package, so they
are built first. And the copy is installed *editable*: pipx runs the files
in your copy instead of its own copies of them, so a change you make takes
effect the next time A2Qlinux starts, without installing again.

1. Install what the build needs, besides the packages above:

   | Distribution | Command |
   |---|---|
   | Arch, CachyOS | `sudo pacman -S --needed clang lld wine` |
   | Debian, Ubuntu | `sudo apt install clang lld libwine-dev` |
   | Fedora | `sudo dnf install clang lld wine-devel` |
   | openSUSE | `sudo zypper install clang lld wine-devel` |

   `clang` and `lld` compile and link the Windows parts; the Wine package
   provides the Windows headers and libraries they are built against.
2. Get the repository and run its installer from it:
   ```
   git clone https://github.com/raman78/A2Qlinux.git && cd A2Qlinux && ./install-from-source.sh --desktop-shortcut
   ```
3. Open a new terminal, so that the A2Qlinux commands are found, and read
   the end of what the installer printed, as in step 4 above.

What `install-from-source.sh` does, in order, with a line `== 1/4 …` and so
on for each step:

| Step | Command it runs | Why |
|---|---|---|
| 1 | `bash bridge/build.sh` | builds the Windows parts into the copy. It finds Wine's files in the folders Arch, Debian, Ubuntu, Fedora and openSUSE use; if something is missing it prints the install command for your distribution |
| 2 | `pipx install --editable .` | installs this copy (the `.` is the current folder); an A2Qlinux installed before is removed first, whether from PyPI or another copy |
| 3 | `pipx ensurepath` | as in step 2 above |
| 4 | `a2qlinux-setup` | the same checks and setup as above; options given to the installer, such as `--desktop-shortcut`, are passed on |

To update your copy later, run `git pull` in it, then `./install-from-source.sh`
again. Changes you make yourself to A2Qlinux's Python files take effect the
next time A2Qlinux starts; after changing the C files in `bridge/`, run the
script again.

Building has been tried on Arch and CachyOS only so far; the other distributions' folders come from their
package file lists. If Wine's files are somewhere else, the build says so;
give the folders as `WINE_INCLUDE=<folder with windows/windows.h>` and
`WINE_LIB=<folder with libkernel32.a>` in front of the command.

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
   "Steam > AION 2 > Properties > General > Launch Options" (if it says
   `Steam launch option: set (…)` instead, this is already done). It looks
   like this, with your user name:
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

1. Quit Questlog from the tray icon. On KDE, if you set up the KDE overlays,
   remove them first with `a2qlinux-setup --no-kde-overlays`.
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
