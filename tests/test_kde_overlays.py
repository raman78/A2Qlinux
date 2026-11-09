import configparser
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from a2qlinux import kde_overlays as k

# Stand-ins for KDE's config tools and dbus-send, so the tests run without
# KDE and never touch the real desktop: kreadconfig6/kwriteconfig6 on INI
# files under $XDG_CONFIG_HOME, dbus-send only recording its call.
FAKE_KCONFIG = r'''#!/usr/bin/env python3
import configparser, os, sys
args = sys.argv[1:]
def value(name):
    return args[args.index(name) + 1]
path = os.path.join(os.environ["XDG_CONFIG_HOME"], value("--file"))
config = configparser.ConfigParser(interpolation=None, delimiters=("=",))
config.optionxform = str
config.read(path)
group, key = value("--group"), value("--key")
if sys.argv[0].endswith("kreadconfig6"):
    print(config.get(group, key, fallback=""))
    sys.exit(0)
if "--delete" in args:
    if config.has_section(group):
        config.remove_option(group, key)
        if not config.options(group):
            config.remove_section(group)
else:
    if not config.has_section(group):
        config.add_section(group)
    config.set(group, key, args[args.index("--key") + 2])
with open(path, "w") as out:
    config.write(out, space_around_delimiters=False)
'''
FAKE_DBUS = '#!/bin/sh\necho "$@" >> "$XDG_CONFIG_HOME/dbus-calls"\necho "   int32 7"\n'

A2TOOLS = "[General]\nOrder=a2tools-overlay,a2tools-no-focus\n\n[a2tools-overlay]\nlayer=overlay\n"


class KdeOverlaysTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.config, self.data, bin_dir = root / "config", root / "data", root / "bin"
        for folder in (self.config, self.data, bin_dir):
            folder.mkdir()
        for name, text in (("kreadconfig6", FAKE_KCONFIG), ("kwriteconfig6", FAKE_KCONFIG),
                           ("dbus-send", FAKE_DBUS)):
            (bin_dir / name).write_text(text)
            (bin_dir / name).chmod(0o755)
        self.saved = {name: os.environ.get(name) for name in ("PATH", "XDG_CONFIG_HOME", "XDG_DATA_HOME",
                                                              "XDG_RUNTIME_DIR")}
        os.environ.update(PATH=f"{bin_dir}:{self.saved['PATH']}", XDG_CONFIG_HOME=str(self.config),
                          XDG_DATA_HOME=str(self.data), XDG_RUNTIME_DIR=str(root))
        self.rules = self.config / "kwinrulesrc"
        self.logged = []

    def tearDown(self):
        for name, value in self.saved.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value
        self.tmp.cleanup()

    def read(self, file="kwinrulesrc"):
        config = configparser.ConfigParser(interpolation=None)
        config.optionxform = str
        config.read(self.config / file)
        return config

    def test_install_appends_to_the_rule_list_and_keeps_other_rules(self):
        self.rules.write_text(A2TOOLS)
        k.install(self.logged.append)
        rules = self.read()
        self.assertEqual(rules["General"]["Order"], f"a2tools-overlay,a2tools-no-focus,{k.RULE}")
        self.assertEqual(rules[k.RULE]["layer"], "overlay")
        self.assertEqual(rules[k.RULE]["title"], k.HUD_TITLE)
        self.assertEqual(rules["a2tools-overlay"]["layer"], "overlay")
        self.assertEqual(self.read("kwinrc")["Plugins"][f"{k.SCRIPT}Enabled"], "true")
        main_js = (k.script_dir() / "contents" / "code" / "main.js").read_text()
        self.assertIn('"steam_app_3393110"', main_js)
        self.assertIn(k.HUD_TITLE, main_js)
        self.assertIn("org.kde.KWin.reconfigure", (self.config / "dbus-calls").read_text())

    def test_installing_again_does_not_list_the_rule_twice(self):
        self.rules.write_text(A2TOOLS)
        k.install(self.logged.append)
        k.install(self.logged.append)
        self.assertEqual(self.read()["General"]["Order"].count(k.RULE), 1)

    def test_remove_leaves_what_was_there_before(self):
        self.rules.write_text(A2TOOLS)
        before = {s: dict(self.read()[s]) for s in self.read().sections()}
        k.install(self.logged.append)
        k.remove(self.logged.append)
        self.assertEqual({s: dict(self.read()[s]) for s in self.read().sections()}, before)
        self.assertFalse(k.script_dir().exists())
        self.assertNotIn("Plugins", self.read("kwinrc").sections())
        calls = (self.config / "dbus-calls").read_text()
        self.assertRegex(calls, rf"(?m)Scripting\.unloadScript string:{k.SCRIPT}$")   # the running script stops
        self.assertIn("Scripting.loadScript", calls)                        # opacity restored

    def test_older_rule_list_is_kept_when_order_is_first_written(self):
        self.rules.write_text("[General]\nrules=old-rule\ncount=1\n\n[old-rule]\nabove=true\n")
        k.install(self.logged.append)
        self.assertEqual(self.read()["General"]["Order"], f"old-rule,{k.RULE}")

    def step(self, want, answer="", interactive=True, env=None):
        asked = []

        def ask(prompt):
            asked.append(prompt)
            return answer
        problem = k.setup_step(want, ask, interactive, self.logged.append,
                               env if env is not None else {"XDG_CURRENT_DESKTOP": "KDE",
                                                            "KDE_SESSION_VERSION": "6"})
        return problem, asked

    def test_asks_with_yes_as_the_default(self):
        problem, asked = self.step(None, answer="")
        self.assertIsNone(problem)
        self.assertEqual(len(asked), 1)
        self.assertIn("[Y/n]", asked[0])
        self.assertTrue(k.installed())
        self.assertTrue(any("Black Market Cards" in line for line in self.logged))   # explained first

    def test_no_means_nothing_is_written(self):
        problem, _ = self.step(None, answer="n")
        self.assertIsNone(problem)
        self.assertFalse(self.rules.exists())
        self.assertFalse(k.script_dir().exists())

    def test_without_a_terminal_nothing_is_written_and_the_command_is_named(self):
        problem, asked = self.step(None, interactive=False)
        self.assertEqual(asked, [])
        self.assertFalse(k.installed())
        self.assertTrue(any("--kde-overlays" in line for line in self.logged))

    def test_other_desktops_get_nothing(self):
        problem, asked = self.step(None, env={"XDG_CURRENT_DESKTOP": "GNOME"})
        self.assertIsNone(problem)
        self.assertEqual(asked, [])
        self.assertFalse(self.rules.exists())
        problem, _ = self.step(True, env={"XDG_CURRENT_DESKTOP": "KDE", "KDE_SESSION_VERSION": "5"})
        self.assertIn("Plasma 6 only", problem)
        self.assertFalse(self.rules.exists())

    def test_set_up_once_it_is_refreshed_without_asking(self):
        self.step(True)
        (k.script_dir() / "contents" / "code" / "main.js").write_text("old version")
        problem, asked = self.step(None)
        self.assertEqual(asked, [])
        self.assertIn("steam_app_3393110", (k.script_dir() / "contents" / "code" / "main.js").read_text())

    def test_no_kde_overlays_removes(self):
        self.step(True)
        self.step(False)
        self.assertFalse(k.installed())

    def test_a_failing_tool_is_a_note_and_nothing_else_breaks(self):
        (Path(self.tmp.name) / "bin" / "kwriteconfig6").write_text("#!/bin/sh\necho 'cannot write' >&2\nexit 1\n")
        problem, _ = self.step(True)
        self.assertIn("cannot write", problem)
        self.assertIn("stay behind the game", problem)


@unittest.skipUnless(shutil.which("kwriteconfig6") and shutil.which("kreadconfig6"), "needs KDE's config tools")
class RealKconfigToolsTest(unittest.TestCase):
    """With KDE's real tools: removing gives back the file byte for byte (KWin itself is not called)."""

    def test_round_trip_is_byte_identical(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            bin_dir = root / "bin"
            bin_dir.mkdir()
            (bin_dir / "dbus-send").write_text(FAKE_DBUS)
            (bin_dir / "dbus-send").chmod(0o755)
            env = dict(os.environ, PATH=f"{bin_dir}:{os.environ['PATH']}", XDG_CONFIG_HOME=str(root),
                       XDG_DATA_HOME=str(root / "data"), XDG_RUNTIME_DIR=tmp)
            original = "[General]\nOrder=a2tools-dps-meter-overlay\n\n[a2tools-dps-meter-overlay]\nlayer=overlay\n"
            (root / "kwinrulesrc").write_text(original)
            code = ("from a2qlinux import kde_overlays as k; k.install(lambda t: None); k.remove(lambda t: None)")
            subprocess.run(["python3", "-c", code], env=env, check=True, cwd=Path(__file__).parent.parent)
            self.assertEqual((root / "kwinrulesrc").read_text(), original)


if __name__ == "__main__":
    unittest.main()
