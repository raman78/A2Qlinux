"""a2qlinux --diagnose [--report]: what A2Qlinux needs, and how the game is started.

Read only: it changes nothing, so it is safe at any time, the game running or
not. Each check gives one line: fine, a note, or a problem with what to do.

    1. A2Qlinux's version, the settings file, Questlog's folder and version.
    2. The checks a2qlinux-setup makes: programs, capture permission, the tray
       icon, the Windows parts (the same functions, a2qlinux.setup_desktop).
    3. Steam: a native installation, the game's prefix, our wpcap.dll in it.
    4. AION 2's Steam launch option, read from each Steam account's
       localconfig.vdf, and whether it ever ran (steam_launch.log).
    5. What runs now: the launcher, Questlog (fed by the bridge or not), the game.
    6. On KDE Plasma 6, whether the KDE overlays are set up.

With --report it also writes a report file: the diagnosis and the end of
launcher.log, with the home folder, user name, Steam account numbers and
network addresses replaced (anonymise). It shows the report and, if the
user agrees, opens a new GitHub issue in the browser with the report filled
in; the user reviews it and submits it with their own account. Nothing is
sent by this program.
"""

import ipaddress
import os
from pathlib import Path
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
                                     "icon and start 'Questlog (AION 2)' from the menu"))
        elif not running:
            results.append((PROBLEM, "Now: Questlog runs with the bridge, but A2Qlinux has ended (status "
                                     "window closed?): it gets no game traffic. Quit it and start it again"))
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


def diagnose(appid=3393110):
    """[(level, text)], in the order of the module docstring."""
    settings, problems = config.load()
    qdir = settings.questlog_dir.expanduser()
    results = [(OK, f"A2Qlinux {shown_version()}"), (OK, f"Settings: {config.CONFIG_PATH}")]
    results += [(PROBLEM, f"Settings: {p}") for p in problems]
    if (qdir / "Questlog.exe").is_file():
        from .update import installed_version
        results.append((OK, f"Questlog: {installed_version(qdir) or 'version unreadable'} in {qdir}"))
    else:
        results.append((PROBLEM, f"Questlog: no Questlog.exe in {qdir}; run a2qlinux-setup"))
    for check in (check_setup, lambda r: check_steam(r, appid, qdir), lambda r: check_running(r, appid), check_kde):
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

    Home folder -> ~, the user name as a path component -> <user>, Steam
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
            text = re.sub(rf"(?<=/){re.escape(self.user)}(?=/|\b)", "<user>", text)
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


def build_report(results, qdir, anonymise):
    logs = qdir / "proton-stream"
    launcher_lines = log_tail(logs / "launcher.log", REPORT_LOG_LINES)
    parts = [f"A2Qlinux report, {time.strftime('%Y-%m-%d %H:%M %Z')}", "", "## Diagnosis", "",
             format_results(results), "", f"## launcher.log (last {REPORT_LOG_LINES} lines)", ""]
    parts += launcher_lines or ["(no launcher.log yet)"]
    parts += ["", "## steam_launch.log (last 10 lines)", ""]
    parts += log_tail(logs / "steam_launch.log", 10) or ["(none)"]
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
