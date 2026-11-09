"""KDE Plasma 6: show Questlog's full-screen overlay layer above AION 2 (docs/ARCHITECTURE.md §6.8).

Questlog draws some overlays - Black Market Cards on the game's own shop
cards, the overlay controls icon - in one transparent window that covers the
whole screen, and in its overlay editing mode (Alt+E) every overlay is drawn
there. Wine hands a window of that size to the window manager, and
KWin keeps the active full-screen game above it, so those overlays stay
hidden behind the game. Questlog's smaller overlay windows (meter, alerts)
are not affected: Wine keeps them out of the window manager's hands.

Two pieces, both installed by a2qlinux-setup with the user's consent and
removed by `a2qlinux-setup --no-kde-overlays`:

- a KWin window rule (group RULE in kwinrulesrc, appended to the rule list
  `Order`) that puts that one window in KWin's overlay layer and never gives
  it focus; it matches Wine's window class `steam_proton` and the window
  title Questlog's page gives it (HUD_TITLE);
- a KWin script (SCRIPT, in ~/.local/share/kwin/scripts) that makes the
  window transparent while AION 2 is not the active window, so the overlays
  do not stay above other programs after Alt+Tab.

Anything that fails here leaves the overlays as they were; nothing else of
A2Qlinux depends on it.
"""

import json
import os
from pathlib import Path
import shutil
import subprocess

APPID = 3393110
RULE = "a2qlinux-questlog-hud"
SCRIPT = "a2qlinux-questlog-hud"
HUD_TITLE = "questlog.gg - Wiki"    # Questlog's default page title: "<domain> - Wiki, Builds, Guides, …"
TOOLS = ("kwriteconfig6", "kreadconfig6", "dbus-send")

RULE_KEYS = {
    "Description": "A2Qlinux: Questlog's full-screen overlay layer above AION 2",
    "wmclass": "steam_proton",
    "wmclassmatch": "1",            # exact
    "wmclasscomplete": "false",
    "title": HUD_TITLE,
    "titlematch": "2",              # substring
    "layer": "overlay",
    "layerrule": "2",               # force
    "acceptfocus": "false",
    "acceptfocusrule": "2",         # force
}

SCRIPT_JS = """\
// A2Qlinux: the window rule "%(rule)s" keeps Questlog's full-screen overlay
// layer above AION 2. This shows the layer only while AION 2 (or the layer
// itself) is the active window, as on Windows, so its overlays do not stay
// above other programs after Alt+Tab.
const GAME = "steam_app_%(appid)d";
function isLayer(w) {
    return !!w && w.resourceClass == "steam_proton" && w.caption.indexOf(%(title)s) >= 0;
}
function apply() {
    const active = workspace.activeWindow;
    const show = !!active && (active.resourceClass == GAME || isLayer(active));
    for (const w of workspace.windowList()) {
        if (isLayer(w)) {
            const opacity = show ? 1.0 : 0.0;
            if (w.opacity != opacity)
                w.opacity = opacity;
        }
    }
}
workspace.windowActivated.connect(apply);
workspace.windowAdded.connect(function (w) {
    w.captionChanged.connect(apply);
    apply();
});
apply();
""" % {"rule": RULE, "appid": APPID, "title": json.dumps(HUD_TITLE)}

METADATA = {
    "KPlugin": {
        "Id": SCRIPT,
        "Name": "A2Qlinux: Questlog overlays above AION 2",
        "Description": "Shows Questlog's full-screen overlay layer only while AION 2 is the active window.",
        "Authors": [{"Name": "A2Qlinux"}],
        "License": "MIT",
        "Version": "1",
    },
    "X-Plasma-API": "javascript",
    "X-Plasma-MainScript": "code/main.js",
    "KPackageStructure": "KWin/Script",
}

EXPLANATION = """\
KDE Plasma: Questlog draws some of its overlays - Black Market Cards on the
shop's cards, the overlay controls icon, and every overlay while you move
them with Alt+E - in one window that covers the whole screen, and KDE keeps
the full-screen game above that window, so you do not see them. A2Qlinux can add a KDE window rule and a small KDE script for that
one window: it is then shown above AION 2 while the game is active, and
hidden when you switch to another program. Nothing else in KDE changes;
`a2qlinux-setup --no-kde-overlays` removes both. Tested on KDE Plasma 6.8.2;
on other versions it may not work, and then the overlays stay as before."""


def script_dir():
    data = os.environ.get("XDG_DATA_HOME") or str(Path.home() / ".local" / "share")
    return Path(data) / "kwin" / "scripts" / SCRIPT


def plasma6(env=os.environ):
    """True on a KDE Plasma 6 (or later) session."""
    desktops = env.get("XDG_CURRENT_DESKTOP", "").upper().split(":")
    version = env.get("KDE_SESSION_VERSION", "")
    return "KDE" in desktops and version.isdigit() and int(version) >= 6


def missing_tools():
    return [tool for tool in TOOLS if not shutil.which(tool)]


def _run(command):
    done = subprocess.run(command, stdin=subprocess.DEVNULL, capture_output=True, text=True, check=False)
    if done.returncode:
        raise RuntimeError(f"{' '.join(command[:1])} failed: {(done.stderr or done.stdout).strip()}")
    return done.stdout.strip()


def _read(file, group, key):
    return _run(["kreadconfig6", "--file", file, "--group", group, "--key", key])


def _write(file, group, key, value):
    _run(["kwriteconfig6", "--file", file, "--group", group, "--key", key, value])


def _delete(file, group, key):
    _run(["kwriteconfig6", "--file", file, "--group", group, "--key", key, "--delete"])


def _rule_list():
    """KWin's rule list. Plasma 6.8 reads `Order`; a file that only has the
    older `rules` list keeps those rules when `Order` is first written."""
    order = _read("kwinrulesrc", "General", "Order")
    if not order:
        order = _read("kwinrulesrc", "General", "rules")
    return [name for name in order.split(",") if name]


def _reconfigure():
    _run(["dbus-send", "--session", "--type=method_call", "--dest=org.kde.KWin", "/KWin",
          "org.kde.KWin.reconfigure"])


def installed():
    return RULE in _rule_list() or script_dir().exists()


def install(log=print):
    """Write (or refresh) the rule and the script, enable the script, reload KWin."""
    for key, value in RULE_KEYS.items():
        _write("kwinrulesrc", RULE, key, value)
    rules = _rule_list()
    if RULE not in rules:
        _write("kwinrulesrc", "General", "Order", ",".join(rules + [RULE]))
    code = script_dir() / "contents" / "code"
    code.mkdir(parents=True, exist_ok=True)
    (script_dir() / "metadata.json").write_text(json.dumps(METADATA, indent=4) + "\n")
    (code / "main.js").write_text(SCRIPT_JS)
    _write("kwinrc", "Plugins", f"{SCRIPT}Enabled", "true")
    _reconfigure()
    log(f"KDE: window rule '{RULE}' in ~/.config/kwinrulesrc and script {script_dir()} are in place.")


RESTORE_JS = """\
for (const w of workspace.windowList())
    if (w.resourceClass == "steam_proton" && w.caption.indexOf(%s) >= 0)
        w.opacity = 1.0;
""" % json.dumps(HUD_TITLE)


def _restore_opacity():
    """Undo the script's transparency on a running Questlog, through a one-off script."""
    path = Path(os.environ.get("XDG_RUNTIME_DIR") or "/tmp") / f"{SCRIPT}-restore.js"
    path.write_text(RESTORE_JS)
    try:
        reply = _run(["dbus-send", "--session", "--print-reply", "--type=method_call", "--dest=org.kde.KWin",
                      "/Scripting", "org.kde.kwin.Scripting.loadScript", f"string:{path}",
                      f"string:{SCRIPT}-restore"])
        number = reply.split()[-1]
        if number.lstrip("-").isdigit() and int(number) >= 0:
            _run(["dbus-send", "--session", "--print-reply", "--type=method_call", "--dest=org.kde.KWin",
                  f"/Scripting/Script{number}", "org.kde.kwin.Script.run"])
        _run(["dbus-send", "--session", "--print-reply", "--type=method_call", "--dest=org.kde.KWin",
              "/Scripting", "org.kde.kwin.Scripting.unloadScript", f"string:{SCRIPT}-restore"])
    finally:
        path.unlink(missing_ok=True)


def remove(log=print):
    """Take out exactly what install wrote, then reload KWin."""
    for key in RULE_KEYS:
        _delete("kwinrulesrc", RULE, key)
    rules = _rule_list()
    if RULE in rules:
        _write("kwinrulesrc", "General", "Order", ",".join(name for name in rules if name != RULE))
    _delete("kwinrc", "Plugins", f"{SCRIPT}Enabled")
    _reconfigure()
    # A reload alone left the script running once its files were gone; unload it by name.
    _run(["dbus-send", "--session", "--print-reply", "--type=method_call", "--dest=org.kde.KWin",
          "/Scripting", "org.kde.kwin.Scripting.unloadScript", f"string:{SCRIPT}"])
    shutil.rmtree(script_dir(), ignore_errors=True)
    _restore_opacity()
    log(f"KDE: removed the window rule '{RULE}' and the script {SCRIPT}.")


def setup_step(want, ask, interactive, log=print, env=os.environ):
    """a2qlinux-setup's step. want: True (--kde-overlays), False (--no-kde-overlays) or None.

    Returns a problem to list, or None.
    """
    try:
        if want is False:
            if installed():
                remove(log)
            else:
                log("KDE overlays: nothing to remove.")
            return None
        if not plasma6(env):
            return "--kde-overlays works on KDE Plasma 6 only" if want else None
        missing = missing_tools()
        if missing:
            return (f"KDE overlays need {', '.join(missing)}, which are part of KDE Plasma and dbus; "
                    "without them Questlog's full-screen overlays stay behind the game")
        if installed():
            install(log)            # refresh to this version's rule and script
            return None
        if not want:
            if not interactive:
                log("KDE overlays are not set up; to show Black Market Cards above the game, run "
                    "a2qlinux-setup --kde-overlays")
                return None
            log("\n" + EXPLANATION)
            answer = ask("Set this up now? [Y/n] ").strip().lower()
            if answer not in ("", "y", "yes", "t", "tak"):
                log("Not set up; run a2qlinux-setup --kde-overlays to do it later.")
                return None
        install(log)
        return None
    except (OSError, RuntimeError) as error:
        return f"KDE overlays: {error}; Questlog's full-screen overlays stay behind the game"
