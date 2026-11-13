"""a2qlinux --diagnose [--report]: what A2Qlinux needs, and how the game is started.

Read only: it changes nothing, so it is safe at any time, the game running or
not. Each check gives one line: fine, a note, or a problem with what to do.

    1. A2Qlinux's version, the system (distribution, kernel, desktop and its
       session type), the graphics cards with their kernel driver and its
       version, what OpenGL renders with, the monitors and the desktop's
       scale, the settings file, Questlog's folder and version.
    2. The checks a2qlinux-setup makes: programs, capture permission, the tray
       icon, the Windows parts (the same functions, a2qlinux.setup_desktop).
    3. Steam: a native installation, the game's prefix, the Proton that last
       ran it, Wine's DPI, Proton/Wine/DXVK/driver variables in Steam's and
       this session's environment, our wpcap.dll in the prefix.
    4. AION 2's Steam launch option, read from each Steam account's
       localconfig.vdf, and whether it ever ran (steam_launch.log).
    5. What runs now: the launcher, Questlog (fed by the bridge or not), the game.
    6. On KDE Plasma 6, whether the KDE overlays are set up.
    7. Whether the game's prefix has a command for Questlog's Open Folder
       buttons, read from its system.reg (no Wine is started).

With --report it also writes a report file: the diagnosis and the end of
launcher.log and of questlog.log and questlog.log.1 (Questlog's and Wine's
output, this run and the one before), with the home folder, user name, Steam account numbers and
network addresses replaced (anonymise). It shows the report and, if the
user agrees, opens a new GitHub issue in the browser with the report filled
in; the user reviews it and submits it with their own account. Nothing is
sent by this program.
"""

import ipaddress
import os
from pathlib import Path
import platform
import re
import shutil
import socket
import subprocess
import sys
import time
import urllib.parse

from . import config, shown_version

OK, NOTE, PROBLEM = "ok", "note", "PROBLEM"
ISSUES_NEW = "https://github.com/raman78/A2Qlinux/issues/new"
# Longest new-issue URL GitHub took, measured 2026-11-10 without being logged
# in (6500 characters went to the login page, 7000 gave an error 500, since
# the login page carries the whole URL along); some margin below that.
ISSUE_URL_LIMIT = 6000
REPORT_LOG_LINES = 400   # lines of launcher.log in the report file: the last few runs
# questlog.log in the report: whole up to HEAD + TAIL lines, else its start (graphics set-up: DXVK's
# device, Chromium's GPU process) and its end (what happened last), with the gap marked.
QUESTLOG_LOG_HEAD, QUESTLOG_LOG_TAIL = 400, 800


# ---------------------------------------------------------------- Steam's files

def parse_vdf(text):
    """Steam's text KeyValues (localconfig.vdf, libraryfolders.vdf) as nested dicts, keys lower-cased.

    Steam writes keys in varying case ("apps", "Apps"), so lookups use lower
    case. A file cut short gives what was read up to there.
    """
    tokens = re.findall(r'"((?:[^"\\]|\\.)*)"|([{}])', text)
    root, stack, key = {}, [], None
    current = root
    for quoted, brace in tokens:
        if brace == "{":
            child = {}
            current[(key or "").lower()] = child
            stack.append(current)
            current, key = child, None
        elif brace == "}":
            if not stack:
                break
            current, key = stack.pop(), None
        elif key is None:
            key = quoted
        else:
            current[key.lower()] = quoted.replace('\\"', '"').replace("\\\\", "\\")
            key = None
    return root


def launch_options(roots, appid):
    """[(account folder, launch option or None)] for every Steam account in these installations."""
    found, seen = [], set()
    for root in roots:
        for local in sorted(Path(root).glob("userdata/*/config/localconfig.vdf")):
            account = local.parent.parent
            if account.resolve() in seen:
                continue
            seen.add(account.resolve())
            try:
                tree = parse_vdf(local.read_text(encoding="utf-8", errors="replace"))
            except OSError:
                found.append((account, None))
                continue
            node = tree
            for key in ("userlocalconfigstore", "software", "valve", "steam", "apps", str(appid)):
                node = node.get(key, {}) if isinstance(node, dict) else {}
            option = node.get("launchoptions") if isinstance(node, dict) else None
            found.append((account, option or None))
    return found


def judge_launch_option(option, ours):
    """(level, text) for one account's launch option; `ours` is this installation's a2qlinux-steam."""
    set_it = f"set it to: {ours} %command%"
    if not option:
        return NOTE, ("not set. The game still starts: A2Qlinux closes Questlog while Steam starts it and "
                      f"opens it again after, which can fail on some systems. To start Questlog with the game, {set_it}")
    words = option.split()
    named = [w for w in words if Path(w).name == "a2qlinux-steam"]
    if not named:
        return NOTE, f"set to something else ({option!r}), without a2qlinux-steam; {set_it}, keeping what is there"
    if "%command%" not in words:
        return PROBLEM, f"{option!r} has no %command%, so Steam never starts the game; {set_it}"
    wrapper = named[0]
    if "/" not in wrapper:
        return PROBLEM, f"{option!r} names a2qlinux-steam without its folder, which Steam cannot find; {set_it}"
    if not Path(wrapper).exists():
        return PROBLEM, f"{option!r} points at {wrapper}, which does not exist (moved or uninstalled?); {set_it}"
    try:
        same = Path(wrapper).resolve() == Path(ours).resolve()
    except OSError:
        same = False
    if not same:
        return NOTE, f"{option!r} runs {wrapper}, not this installation's {ours}"
    return OK, option


# ---------------------------------------------------------------- checks

DESKTOP_VERSION = {"KDE": ["plasmashell", "--version"], "GNOME": ["gnome-shell", "--version"]}
VERSION_WAIT = 5    # s for a desktop's --version


def system_lines(env=os.environ, os_info=None, kernel=None, run=subprocess.run):
    """[(OK, text)]: the distribution, the kernel, the desktop with its version where it says, the session type."""
    from .setup_desktop import os_release
    info = os_release() if os_info is None else os_info
    distro = info.get("PRETTY_NAME") or " ".join(filter(None, (info.get("NAME"), info.get("VERSION_ID"))))
    desktop = env.get("XDG_CURRENT_DESKTOP") or env.get("DESKTOP_SESSION") or "unknown (no XDG_CURRENT_DESKTOP)"
    version = ""
    for name, command in DESKTOP_VERSION.items():
        if name in desktop.upper().split(":") and shutil.which(command[0]):
            try:
                done = run(command, stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=VERSION_WAIT)
                version = done.stdout.strip().splitlines()[0] if done.stdout.strip() else ""
            except (OSError, subprocess.TimeoutExpired):
                version = ""
            break
    session = env.get("XDG_SESSION_TYPE") or "unknown session type"
    return [(OK, f"System: {distro or 'unknown distribution (no /etc/os-release)'}, "
                 f"kernel {kernel or platform.release()}"),
            (OK, f"Desktop: {desktop}{f' ({version})' if version else ''}, {session}")]


PCI_IDS = ("/usr/share/hwdata/pci.ids", "/usr/share/misc/pci.ids", "/usr/share/pci.ids")
GLXINFO_WAIT = 5    # s for glxinfo -B


def pci_name(vendor, device, ids_files=PCI_IDS):
    """(vendor name, device name) from the pci.ids database; the hex ids where it has no entry."""
    vendor, device = vendor.lower().removeprefix("0x"), device.lower().removeprefix("0x")
    for path in ids_files:
        try:
            lines = Path(path).read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            continue
        vendor_name, device_name, inside = None, None, False
        for line in lines:
            if not line or line.startswith("#"):
                continue
            if not line.startswith("\t"):
                if inside:
                    break
                inside = line[:4].lower() == vendor
                if inside:
                    vendor_name = line[4:].strip()
            elif inside and not line.startswith("\t\t") and line[1:5].lower() == device:
                device_name = line[5:].strip()
                break
        if vendor_name:
            return vendor_name, device_name or f"device {device}"
    return f"vendor {vendor}", f"device {device}"


def gpu_lines(sys_root="/", run=subprocess.run, ids_files=PCI_IDS, which=shutil.which):
    """[(level, text)]: each graphics card with its kernel driver (and NVIDIA's version), and OpenGL's renderer.

    Questlog draws with Chromium on the GPU, so a window that stays black, or
    overlays that do, are first of all a question of card and driver.
    """
    root = Path(sys_root)
    lines = []
    for card in sorted((root / "sys/class/drm").glob("card[0-9]*")):
        if "-" in card.name:
            continue                       # a connector (card1-DP-1), not a card
        device = card / "device"
        try:
            vendor_id = (device / "vendor").read_text().strip()
            device_id = (device / "device").read_text().strip()
        except OSError:
            continue
        driver = os.path.basename(os.readlink(device / "driver")) if (device / "driver").is_symlink() else "no driver"
        vendor, model = pci_name(vendor_id, device_id, ids_files)
        version = ""
        if driver == "nvidia":
            try:
                found = re.search(r"Kernel Module.*?\s(\d+\.\d+(?:\.\d+)?)\s",
                                  (root / "proc/driver/nvidia/version").read_text())
                version = f" {found.group(1)}" if found else ""
            except OSError:
                pass
        try:
            primary = (device / "boot_vga").read_text().strip() == "1"
        except OSError:
            primary = False
        lines.append((OK, f"Graphics: {vendor} {model}, driver {driver}{version}" + (" (primary)" if primary else "")))
    if not lines:
        lines.append((NOTE, "Graphics: no card found under /sys/class/drm"))
    if which("glxinfo"):
        try:
            done = run(["glxinfo", "-B"], stdin=subprocess.DEVNULL, capture_output=True, text=True,
                       timeout=GLXINFO_WAIT)
            found = dict(re.findall(r"^OpenGL (renderer|version) string: (.+)$", done.stdout, re.MULTILINE))
        except (OSError, subprocess.TimeoutExpired):
            found = {}
        if not found:
            lines.append((NOTE, "OpenGL: unknown (glxinfo -B gave no renderer; no desktop session here?)"))
        else:
            renderer = found.get("renderer", "?")
            software = any(name in renderer.lower() for name in ("llvmpipe", "softpipe", "swrast"))
            lines.append((NOTE if software else OK, f"OpenGL: {renderer}, {found.get('version', '?')}"
                          + (" - software rendering: the graphics driver is not in use" if software else "")))
    else:
        lines.append((NOTE, "OpenGL: unknown (glxinfo is not installed)"))
    return lines


XRANDR_WAIT = 5    # s for xrandr / kscreen-doctor
# Environment variables that change how Proton, Wine, DXVK or the graphics driver behave.
ENV_PREFIXES = ("PROTON_", "DXVK_", "VKD3D_", "WINE", "__GL_", "__GLX_", "MESA_", "RADV_", "AMD_VULKAN",
                "VK_ICD_FILENAMES", "VK_DRIVER_FILES", "VK_LOADER", "DRI_PRIME", "ENABLE_VKBASALT",
                "MANGOHUD", "LD_PRELOAD", "SDL_VIDEODRIVER", "STEAM_COMPAT_")


def display_lines(env=os.environ, run=subprocess.run, which=shutil.which, home=None):
    """[(level, text)]: the monitors as X11 programs (Wine, so Questlog) see them, and the desktop's scale.

    Wine draws through X11 (XWayland in a Wayland session), so `xrandr` shows
    the screens and positions Questlog places its overlays on. The scale is
    the desktop's own: KDE's from kscreen-doctor, GNOME's from monitors.xml.
    """
    lines = []
    if which("xrandr") and env.get("DISPLAY"):
        try:
            done = run(["xrandr", "--listmonitors"], stdin=subprocess.DEVNULL, capture_output=True, text=True,
                       timeout=XRANDR_WAIT)
            monitors = re.findall(r"^\s*\d+: [+*]*(\S+) (\d+)/\d+x(\d+)/\d+([+-]\d+[+-]\d+)", done.stdout,
                                  re.MULTILINE)
        except (OSError, subprocess.TimeoutExpired):
            monitors = []
        lines.append((OK, "Monitors (as Wine sees them): "
                      + ", ".join(f"{name} {w}x{h} at {pos}" for name, w, h, pos in monitors)) if monitors else
                     (NOTE, "Monitors: unknown (xrandr --listmonitors gave none)"))
    elif not env.get("DISPLAY"):
        lines.append((NOTE, "Monitors: unknown (no X11 display here; run this in the desktop session)"))
    else:
        lines.append((NOTE, "Monitors: unknown (xrandr is not installed)"))
    desktop = env.get("XDG_CURRENT_DESKTOP", "").upper().split(":")
    scales = []
    if "KDE" in desktop and which("kscreen-doctor"):
        try:
            done = run(["kscreen-doctor", "-j"], stdin=subprocess.DEVNULL, capture_output=True, text=True,
                       timeout=XRANDR_WAIT)
            import json
            scales = [f"{o['name']} {o.get('scale', 1):g}" for o in json.loads(done.stdout).get("outputs", [])
                      if o.get("enabled")]
        except (OSError, subprocess.TimeoutExpired, ValueError, KeyError, TypeError):
            scales = []
    elif "GNOME" in desktop:
        xml = Path(home or Path.home()) / ".config" / "monitors.xml"
        try:
            found = re.findall(r"<scale>([\d.]+)</scale>", xml.read_text(errors="replace"))
            scales = [f"{float(value):g}" for value in found] or ["1"]
        except OSError:
            scales = ["1 (no monitors.xml: never changed)"]
    if scales:
        lines.append((OK, "Desktop scale: " + ", ".join(scales)))
    elif "KDE" in desktop:
        lines.append((NOTE, "Desktop scale: unknown (kscreen-doctor is missing or gave no outputs)"))
    elif "GNOME" not in desktop:
        lines.append((NOTE, "Desktop scale: unknown on this desktop (read on KDE and GNOME only)"))
    return lines


def wine_dpi_line(prefix):
    """(OK, text): the DPI values set in the prefix's registry, each with its key (96 is 100 %)."""
    found = []
    for name, key in (("user.reg", r"[Control Panel\\Desktop]"), ("user.reg", r"[Software\\Wine\\Fonts]"),
                      ("system.reg", r"[System\\CurrentControlSet\\Hardware Profiles\\Current\\Software\\Fonts]"),
                      ("system.reg", r"[System\\ControlSet001\\Hardware Profiles\\Current\\Software\\Fonts]")):
        try:
            text = (Path(prefix) / name).read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        start = text.find("\n" + key + " ")
        if start < 0:
            continue
        end = text.find("\n[", start + 1)
        value = re.search(r'^"LogPixels"=dword:([0-9a-fA-F]+)$', text[start:end if end > 0 else None], re.MULTILINE)
        if value:
            shown = key.strip("[]").replace("\\\\", "\\")
            found.append(f"{int(value.group(1), 16)} in {shown}")
    return OK, "Wine DPI: " + ("; ".join(found) if found else "not set (Wine's default, 96)")


def env_settings(environ):
    """The entries of `environ` (a dict) that change how Proton, Wine, DXVK or the driver behave, sorted."""
    return sorted(f"{k}={v}" for k, v in environ.items() if k.startswith(ENV_PREFIXES))


STEAM_PROGRAMS = (b"/steam.sh", b"/steamrt64/steam", b"/ubuntu12_64/steam", b"/ubuntu12_32/steam")


def steam_environment(proc="/proc"):
    """The Steam client's environment as a dict, None when Steam is not running.

    steam.sh's is preferred (run as `bash …/steam.sh`): it is what the
    session handed to Steam, before Steam's own runtime adds to it.
    """
    found = {}
    with os.scandir(proc) as entries:
        for entry in entries:
            if not entry.name.isdigit():
                continue
            try:
                argv = Path(entry.path, "cmdline").read_bytes().split(b"\0")[:2]
                program = next((STEAM_PROGRAMS.index(p) for p in STEAM_PROGRAMS for a in argv if a.endswith(p)), None)
                if program is None or program in found:
                    continue
                raw = Path(entry.path, "environ").read_bytes()
            except OSError:
                continue
            found[program] = dict(item.split("=", 1) for item in raw.decode("utf-8", "replace").split("\0")
                                  if "=" in item)
    return found[min(found)] if found else None


def environment_lines(env=os.environ, steam_environ=False):
    """[(level, text)]: such variables in Steam's environment (what the game starts with) and in this session's."""
    def listed(environ):
        settings = env_settings(environ)
        return ", ".join(settings) if settings else "no Proton, Wine, DXVK or driver variables"
    steam = steam_environment() if steam_environ is False else steam_environ
    return [(OK, "Steam's environment: " + (listed(steam) if steam is not None else "unknown (Steam is not running)")),
            (OK, "This session's environment (Questlog's): " + listed(env))]


def proton_line(prefix, host_root="/"):
    """(level, text): the Proton that last ran the prefix.

    Proton rewrites config_info beside the prefix on a start whenever it
    differs. Its first line is the prefix's format version
    (CURRENT_PREFIX_VERSION, e.g. "11.0-100"), which many builds share; the
    lines below are paths inside the Proton tool's folder, as the Steam
    runtime container sees them (/run/host/... is the host's /...). The
    build's own name is in that folder's `version` file ("<time> <name>").
    """
    try:
        lines = (Path(prefix).parent / "config_info").read_text(errors="replace").splitlines()
    except OSError:
        return NOTE, "Proton: unknown (no config_info next to the prefix; the game not started yet?)"
    prefix_version = lines[0].strip() if lines else ""
    folder = next((line.split("/files/", 1)[0] for line in lines[1:] if "/files/" in line), "")
    if folder.startswith("/run/host/"):
        folder = folder[len("/run/host"):]
    build = ""
    if folder:
        try:
            build = (Path(host_root) / folder.lstrip("/") / "version").read_text(errors="replace").split()[-1]
        except (OSError, IndexError):
            build = ""
    if not (build or prefix_version):
        return NOTE, "Proton: unknown (config_info is empty)"
    tool = Path(folder).name if folder else ""
    shown = build or f"build unknown, prefix version {prefix_version}"
    return OK, f"Proton (last run): {shown}" + (f" (folder {tool})" if tool else "")


def check_setup(results):
    from . import setup_desktop as setup
    info = setup.os_release()
    missing, wanted = setup.missing_packages()
    commands = setup.install_commands(wanted, info)
    if missing or commands:
        results.append((PROBLEM, "Programs: missing " + "; ".join(missing or ["a library"])
                        + "".join(f" - install with: {line}" for line in commands)))
    else:
        results.append((OK, "Programs: all there"))
    capture = setup.capture_problem(info)
    results.append((PROBLEM, f"Capture: {capture}") if capture else (OK, "Capture: allowed"))
    tray = setup.tray_problem()
    results.append((PROBLEM, f"Tray icon: {tray}") if tray else (OK, "Tray icon: can run"))
    parts = setup.windows_parts_problem()
    results.append((PROBLEM, f"Windows parts: {parts}") if parts else (OK, "Windows parts: present"))


def check_steam(results, appid, qdir):
    from . import launcher
    from .setup_desktop import command
    roots = launcher.steam_roots()
    if roots:
        results.append((OK, "Steam: " + ", ".join(map(str, roots))))
    elif launcher.FLATPAK_STEAM.is_dir():
        results.append((PROBLEM, "Steam: only a Flatpak Steam was found; A2Qlinux needs Steam from the "
                                 "distribution or from Valve (docs/INSTALL.md)"))
    else:
        results.append((PROBLEM, "Steam: no installation found"))
    try:
        prefix = launcher.game_prefix(appid, roots)
        results.append((OK, f"Game prefix: {prefix}"))
        results.append(proton_line(prefix))
        results.append(wine_dpi_line(prefix))
        results += environment_lines()
        dll = prefix / "drive_c" / "windows" / "system32" / "Npcap" / "wpcap.dll"
        try:
            ours = launcher.BRIDGE_SIGNATURE in dll.read_bytes()
            results.append((OK, "wpcap.dll in the prefix: A2Qlinux's") if ours else
                           (PROBLEM, f"wpcap.dll in the prefix: {dll} is not A2Qlinux's (a real Npcap?); "
                                     "the launcher leaves it alone and Questlog gets no traffic"))
        except FileNotFoundError:
            results.append((NOTE, "wpcap.dll in the prefix: not there yet; the launcher puts it there on start"))
    except RuntimeError as error:
        results.append((PROBLEM, f"Game prefix: {error}"))

    try:
        ours = command("a2qlinux-steam")
    except RuntimeError as error:
        results.append((PROBLEM, f"Launch option: {error}"))
        ours = "a2qlinux-steam"
    accounts = launch_options(roots, appid)
    if not accounts:
        results.append((NOTE, "Launch option: no Steam account's settings found (Steam not used yet?)"))
    for account, option in accounts:
        level, text = judge_launch_option(option, ours)
        label = "Launch option" + (f" ({account})" if len(accounts) > 1 else "")
        results.append((level, f"{label}: {text}"))

    runs = qdir / "proton-stream" / "steam_launch.log"
    try:
        last = runs.read_text(errors="replace").strip().splitlines()[-1]
        level = NOTE if "not running" in last else OK
        results.append((level, f"Launch option last ran: {last}"))
    except (FileNotFoundError, IndexError):
        results.append((NOTE, "Launch option last ran: never (no steam_launch.log)"))
    except OSError as error:
        results.append((NOTE, f"Launch option last ran: {runs} unreadable: {error}"))


def check_running(results, appid):
    from . import launcher
    from .desktop import launcher_pid, launcher_running
    running = launcher_running()
    pid = launcher_pid()
    procs = launcher.game_processes(appid, ["questlog.exe", "aion2.exe"])
    questlog, game = procs["questlog.exe"], procs["aion2.exe"]
    results.append((OK, f"Now: A2Qlinux is running (launcher PID {pid})" if running else "Now: A2Qlinux is not running"))
    if questlog:
        fed = any("QUESTLOG_PROTON_BRIDGE=" in launcher._read(f"/proc/{p}/environ") for p in questlog)
        if not fed:
            results.append((PROBLEM, "Now: Questlog runs, but was not started by A2Qlinux: it gets no game "
                                     "traffic, and the game waits until it is closed. Quit it from its own tray "
                                     "icon and start 'A2Qlinux' from the menu"))
        elif not running:
            results.append((PROBLEM, "Now: Questlog runs with the bridge, but A2Qlinux has ended (status "
                                     "window closed?): it gets no game traffic. Start 'A2Qlinux' from the menu: "
                                     "it closes this Questlog and starts it again"))
        else:
            results.append((OK, "Now: Questlog runs under A2Qlinux"))
    else:
        results.append((OK, "Now: Questlog is not running"))
    results.append((OK, "Now: AION 2 is running" if game else "Now: AION 2 is not running"))


def check_kde(results):
    from . import kde_overlays
    if not kde_overlays.plasma6():
        return
    if kde_overlays.installed():
        results.append((OK, "KDE overlays: set up"))
    else:
        results.append((NOTE, "KDE overlays: not set up; Black Market Cards stays hidden behind the game "
                              "(a2qlinux-setup --kde-overlays)"))


def check_open_folders(results, appid, prefix=None):
    from . import launcher, open_folders
    try:
        prefix = prefix or launcher.game_prefix(appid)
    except RuntimeError:
        return                          # reported by check_steam
    state, value = open_folders.registry_state(prefix / "system.reg")
    if state == "ours":
        results.append((OK, "Open Folder: set up; Questlog's folders open in the file manager"))
    elif state == "other":
        results.append((NOTE, f"Open Folder: the prefix has another command for opening folders "
                              f"({value or 'a key without a command'}); A2Qlinux leaves it as it is"))
    else:
        results.append((NOTE, "Open Folder: not set up; Questlog's Open Folder buttons show Wine's \"no Windows "
                              "program configured\" (a2qlinux-setup --open-folders; a change made in the last "
                              "30 s may not be saved to the prefix yet)"))


def diagnose(appid=3393110):
    """[(level, text)], in the order of the module docstring."""
    settings, problems = config.load()
    qdir = settings.questlog_dir.expanduser()
    results = [(OK, f"A2Qlinux {shown_version()}")]
    try:
        results += system_lines()
        results += gpu_lines()
        results += display_lines()
    except Exception as error:         # as below: reported, never hiding the rest
        results.append((PROBLEM, f"This check failed: {error!r} (please report it)"))
    results.append((OK, f"Settings: {config.CONFIG_PATH}"))
    results += [(PROBLEM, f"Settings: {p}") for p in problems]
    if (qdir / "Questlog.exe").is_file():
        from .update import installed_version
        results.append((OK, f"Questlog: {installed_version(qdir) or 'version unreadable'} in {qdir}"))
    else:
        results.append((PROBLEM, f"Questlog: no Questlog.exe in {qdir}; run a2qlinux-setup"))
    for check in (check_setup, lambda r: check_steam(r, appid, qdir), lambda r: check_running(r, appid), check_kde,
                  lambda r: check_open_folders(r, appid)):
        try:
            check(results)
        except Exception as error:     # one broken check must not hide the others; it is reported
            results.append((PROBLEM, f"This check failed: {error!r} (please report it)"))
    return results, qdir


def format_results(results):
    width = max(len(level) for level, _ in results)
    return "\n".join(f"{level:<{width}}  {text}" for level, text in results)


# ---------------------------------------------------------------- anonymising

class Anonymiser:
    """Replaces what identifies the user or their network, the same value always the same way.

    Home folder -> ~, the user name as a path component (also in Wine's Windows paths) -> <user>, Steam
    account folders -> userdata/<steam-id-N>, the host name -> <host>,
    IPv4 and IPv6 addresses -> <private-N> / <public-N> / <ipv6-N> (loopback
    and 0.0.0.0 stay, they say nothing about anyone). A consistent
    placeholder keeps the report readable: "the game uses <private-2>" still
    matches the line where <private-2> was captured on.
    """

    IPV4 = re.compile(r"(?<![\d.])(\d{1,3}(?:\.\d{1,3}){3})(?!\d|\.\d)")   # a full stop after it ends a sentence
    # Home and VPN networks (RFC 1918, carrier-grade NAT as Tailscale uses, link-local); anything else is public.
    PRIVATE = [ipaddress.ip_network(n) for n in ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16",
                                                 "100.64.0.0/10", "169.254.0.0/16")]
    IPV6 = re.compile(r"(?<![0-9A-Fa-f:])((?:[0-9A-Fa-f]{0,4}:){2,7}[0-9A-Fa-f]{0,4})(?![0-9A-Fa-f:])")
    STEAM_ID = re.compile(r"(userdata/)(\d+)")

    def __init__(self, home=None, user=None, host=None):
        self.home = str(home or Path.home())
        self.user = user or os.environ.get("USER") or Path(self.home).name
        self.host = host if host is not None else socket.gethostname()
        self.names = {}

    def _name(self, kind, value):
        key = (kind, value)
        if key not in self.names:
            self.names[key] = f"<{kind}-{sum(1 for k, _ in self.names if k == kind) + 1}>"
        return self.names[key]

    def _ipv4(self, match):
        try:
            address = ipaddress.ip_address(match.group(1))
        except ValueError:
            return match.group(0)
        if address.is_loopback or address.is_unspecified:
            return match.group(0)
        private = any(address in network for network in self.PRIVATE)
        return self._name("private" if private else "public", str(address))

    def _ipv6(self, match):
        try:
            address = ipaddress.ip_address(match.group(1))
        except ValueError:
            return match.group(0)
        if address.is_loopback or address.is_unspecified:
            return match.group(0)
        return self._name("ipv6", str(address))

    def __call__(self, text):
        for home in {self.home, os.path.realpath(self.home)}:
            text = text.replace(home, "~")
        if self.user:
            # Linux paths, and Wine's Windows ones (Z:\home\<user>\..., also with doubled backslashes)
            text = re.sub(rf"(?<=[/\\]){re.escape(self.user)}(?=[/\\]|\b)", "<user>", text)
        text = self.STEAM_ID.sub(lambda m: m.group(1) + self._name("steam-id", m.group(2)), text)
        if self.host and len(self.host) >= 3:
            text = re.sub(rf"\b{re.escape(self.host)}\b", "<host>", text)
        text = self.IPV4.sub(self._ipv4, text)
        return self.IPV6.sub(self._ipv6, text)


# ---------------------------------------------------------------- report

def log_tail(path, lines):
    try:
        return path.read_text(errors="replace").splitlines()[-lines:]
    except OSError:
        return []


def questlog_log_excerpt(path, head=QUESTLOG_LOG_HEAD, tail=QUESTLOG_LOG_TAIL):
    """questlog.log's lines for the report: all of them, or its start and end with the gap marked."""
    try:
        lines = path.read_text(errors="replace").splitlines()
    except OSError:
        return []
    if len(lines) <= head + tail:
        return lines
    return lines[:head] + [f"(... {len(lines) - head - tail} lines left out ...)"] + lines[-tail:]


def build_report(results, qdir, anonymise):
    logs = qdir / "proton-stream"
    launcher_lines = log_tail(logs / "launcher.log", REPORT_LOG_LINES)
    parts = [f"A2Qlinux report, {time.strftime('%Y-%m-%d %H:%M %Z')}", "", "## Diagnosis", "",
             format_results(results), "", f"## launcher.log (last {REPORT_LOG_LINES} lines)", ""]
    parts += launcher_lines or ["(no launcher.log yet)"]
    parts += ["", "## steam_launch.log (last 10 lines)", ""]
    parts += log_tail(logs / "steam_launch.log", 10) or ["(none)"]
    parts += ["", "## questlog.log (Questlog's and Wine's output since A2Qlinux last started it)", ""]
    parts += questlog_log_excerpt(logs / "questlog.log") or ["(none)"]
    parts += ["", "## questlog.log.1 (the run before that)", ""]
    parts += questlog_log_excerpt(logs / "questlog.log.1", head=200, tail=400) or ["(none)"]
    return anonymise("\n".join(parts) + "\n")


def issue_url(results, report, report_path, anonymise, limit=ISSUE_URL_LIMIT):
    """A new-issue URL with the diagnosis and as much of the log's end as fits within `limit`."""
    title = f"Problem report (A2Qlinux {shown_version()})"
    diagnosis = anonymise(format_results(results)).splitlines()
    log_lines = report.split("## launcher.log", 1)[-1].split("## steam_launch.log", 1)[0].strip().splitlines()[1:]
    log_lines = [line for line in log_lines if line.strip()]

    def head(lines):
        cut = "" if len(lines) == len(diagnosis) else "(cut here; the rest is in the attached report)\n"
        return ("**What happened, and roughly when:**\n\n\n\n"
                f"**Full report:** please attach `{anonymise(str(report_path))}` (drag it into this box).\n\n"
                "### Diagnosis\n\n```\n" + "".join(f"{line}\n" for line in lines) + cut + "```\n")

    def url(body):
        return ISSUES_NEW + "?" + urllib.parse.urlencode({"title": title, "body": body})

    full = head(diagnosis)
    for keep in range(len(log_lines), 0, -1):          # as much of the log's end as fits
        candidate = (full + f"\n### launcher.log (last {keep} lines)\n\n```\n"
                     + "\n".join(log_lines[-keep:]) + "\n```\n")
        if len(url(candidate)) <= limit:
            return url(candidate)
    lines = list(diagnosis)                            # no log line fits: the diagnosis, shortened if need be
    while lines and len(url(head(lines))) > limit:
        lines.pop()
    return url(head(lines))


def report(results, qdir, ask=input, interactive=None, opener=None):
    interactive = sys.stdin.isatty() if interactive is None else interactive
    anonymise = Anonymiser()
    text = build_report(results, qdir, anonymise)
    path = Path.home() / f"a2qlinux-report-{time.strftime('%Y%m%d-%H%M%S')}.txt"
    path.write_text(text)
    print("\n" + text)
    print(f"Report written to {path}.\nHome folder, user name, host name, Steam account numbers and network "
          "addresses are replaced; read it above before you share it.")
    if not interactive:
        print(f"To report a problem, open {ISSUES_NEW} and attach that file.")
        return 0
    answer = ask("\nOpen a new GitHub issue in your browser with this report? It will be public. [y/N] ")
    if answer.strip().lower() not in ("y", "yes"):
        print(f"Not opened. To report later, open {ISSUES_NEW} and attach {path}.")
        return 0
    url = issue_url(results, text, path, anonymise)
    opener = opener or open_in_browser
    if not opener(url):
        print(f"No browser could be started. Open this address yourself:\n{url}")
    else:
        print(f"Opened in your browser. Log in, attach {path}, describe what happened, then submit.")
    return 0


def open_in_browser(url):
    found = shutil.which("xdg-open")
    if not found:
        return False
    try:
        subprocess.Popen([found, url], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL, start_new_session=True)
    except OSError:
        return False
    return True


def main(argv):
    results, qdir = diagnose()
    print(format_results(results))
    problems = sum(1 for level, _ in results if level == PROBLEM)
    print(f"\n{problems} problem(s)." if problems else "\nNo problems found.")
    if "--report" in argv:
        report(results, qdir)
    return 1 if problems else 0
