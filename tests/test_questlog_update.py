import base64
import hashlib
import json
from pathlib import Path
import shutil
import struct
import subprocess
import tempfile
import unittest

import questlog_update as u

FEED_0134 = """version: 0.1.34
files:
  - url: questlog-setup-0.1.34.exe
    sha512: KN8k3tSLWZhtij6zJItF9frvbXDXN7/jhjDbjfA9eeQPHjB7Sfw9qGKyudd7uUVQeYHbo2RvJzKJYa6jW8g5cA==
    size: 115852568
    isAdminRightsRequired: true
path: questlog-setup-0.1.34.exe
sha512: KN8k3tSLWZhtij6zJItF9frvbXDXN7/jhjDbjfA9eeQPHjB7Sfw9qGKyudd7uUVQeYHbo2RvJzKJYa6jW8g5cA==
releaseDate: '2026-10-18T11:10:38.625Z'
"""

GOOD_MAIN = 'x.app.on("second-instance",l.show);w=new B({focusable:!1,alwaysOnTop:!0});'
GOOD_WORKER = " ".join(f"{name}(a)" for name in sorted(u.PCAP_CALLS))


def write_asar(path, files):
    """A minimal app.asar with the given {path: bytes}, in Electron's layout."""
    tree, data, offset = {"files": {}}, b"", 0
    for name, content in files.items():
        node = tree
        parts = name.split("/")
        for part in parts[:-1]:
            node = node["files"].setdefault(part, {"files": {}})
        node["files"][parts[-1]] = {"size": len(content), "offset": str(offset)}
        data += content
        offset += len(content)
    header = json.dumps(tree).encode()
    pickle = struct.pack("<II", len(header) + 4, len(header)) + header
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(struct.pack("<II", 4, len(pickle)) + pickle + data)


def make_app(folder, version="0.1.35", electron="44.5.1", main=GOOD_MAIN, worker=GOOD_WORKER):
    """An unpacked Questlog with just what A2Qlinux looks at."""
    (folder / "resources").mkdir(parents=True)
    (folder / "Questlog.exe").write_bytes(b"MZ ... Chrome/1 Electron/" + electron.encode() + b" ...")
    (folder / "resources" / "app-update.yml").write_text("provider: generic\n")
    write_asar(folder / "resources" / "app.asar", {
        "package.json": json.dumps({"version": version}).encode(),
        ".output/electron/main.cjs": main.encode(),
        ".output/electron/workers/aion-2/combat.cjs": worker.encode(),
        "resources/icon.png": b"\x89PNG",
    })
    return folder


class FeedTest(unittest.TestCase):
    def test_reads_electron_builder_feed(self):
        feed = u.parse_feed(FEED_0134)
        self.assertEqual(feed["version"], "0.1.34")
        self.assertEqual(feed["path"], "questlog-setup-0.1.34.exe")
        self.assertEqual(feed["size"], 115852568)
        self.assertTrue(feed["sha512"].startswith("KN8k3t"))

    def test_refuses_a_path_outside_the_download_folder(self):
        with self.assertRaises(ValueError):
            u.parse_feed(FEED_0134.replace("path: questlog-setup-0.1.34.exe", "path: ../evil.exe"))

    def test_refuses_an_incomplete_feed(self):
        with self.assertRaises(ValueError):
            u.parse_feed("version: 0.1.34\n")

    def test_versions_compare_numerically(self):
        self.assertGreater(u.version_key("0.1.100"), u.version_key("0.1.34"))
        self.assertGreater(u.version_key("0.1.34"), u.version_key("0.1.29"))


class CompatibilityTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_a_fitting_version_has_no_problems(self):
        app = make_app(self.root / "app")
        self.assertEqual(u.compatibility_problems(app), [])
        self.assertEqual(u.installed_version(app), "0.1.35")

    def test_new_pcap_call_unknown_electron_and_lost_behaviours_are_reported(self):
        app = make_app(self.root / "app", electron="45.0.0", main="nothing relevant",
                       worker=GOOD_WORKER + " pcap_sendpacket(a)")
        problems = " | ".join(u.compatibility_problems(app))
        self.assertIn("pcap_sendpacket", problems)
        self.assertIn("Electron 45.0.0", problems)
        self.assertIn("second start", problems)
        self.assertIn("non-activatable", problems)


class StageInstallRollbackTest(unittest.TestCase):
    """The whole path, offline: feed and installer come from file:// URLs."""

    def setUp(self):
        if not shutil.which("7z"):
            self.skipTest("7z not installed")
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.questlog = make_app(root / "Questlog", version="0.1.34")
        self.state = self.questlog / "proton-stream"
        self.state.mkdir()
        (self.state / ".lock").write_text("123\n")
        # An "installer" laid out like Questlog's NSIS one: $PLUGINSDIR/app-64.7z.
        self.cdn = root / "cdn"
        build = root / "build"
        make_app(build / "app", version="0.1.35")
        (build / "nsis" / "$PLUGINSDIR").mkdir(parents=True)
        subprocess.run(["7z", "a", str(build / "nsis" / "$PLUGINSDIR" / "app-64.7z"), "."],
                       cwd=build / "app", check=True, capture_output=True)
        self.cdn.mkdir()
        installer = self.cdn / "questlog-setup-0.1.35.exe"
        subprocess.run(["7z", "a", "-t7z", str(installer), "$PLUGINSDIR"], cwd=build / "nsis",
                       check=True, capture_output=True)
        digest = base64.b64encode(hashlib.sha512(installer.read_bytes()).digest()).decode()
        (self.cdn / "latest.yml").write_text(
            FEED_0134.replace("0.1.34", "0.1.35").replace("115852568", str(installer.stat().st_size))
            .replace("KN8k3tSLWZhtij6zJItF9frvbXDXN7/jhjDbjfA9eeQPHjB7Sfw9qGKyudd7uUVQeYHbo2RvJzKJYa6jW8g5cA==", digest))
        self.logged, self.notified = [], []

    def tearDown(self):
        self.tmp.cleanup()

    def stage(self):
        return u.stage(self.questlog, self.state, self.logged.append, self.notified.append,
                       feed_url=(self.cdn / "latest.yml").as_uri(), downloads=self.cdn.as_uri() + "/")

    def test_stage_install_and_roll_back(self):
        state = self.stage()
        self.assertTrue(state["fits"], self.logged)
        self.assertEqual(len(self.notified), 1)
        self.assertFalse((Path(state["app"]) / "resources" / "app-update.yml").exists())

        old, backup = u.install_staged(self.questlog, self.state, self.logged.append)
        self.assertEqual(old, "0.1.34")
        self.assertEqual(u.installed_version(self.questlog), "0.1.35")
        self.assertEqual(u.installed_version(backup), "0.1.34")
        self.assertEqual((self.state / ".lock").read_text(), "123\n")      # state folder moved across
        self.assertFalse((self.state / "update").exists())
        self.assertFalse((backup / "proton-stream").exists())

        self.assertTrue(u.rollback(self.questlog, self.state, self.logged.append))
        self.assertEqual(u.installed_version(self.questlog), "0.1.34")
        self.assertEqual((self.state / ".lock").read_text(), "123\n")
        # The failed version is remembered and not fetched again.
        self.assertIsNotNone(self.stage())
        self.assertFalse(u.read_state(self.state)["fits"])
        self.assertIsNone(u.install_staged(self.questlog, self.state, self.logged.append))

    def test_a_corrupt_download_is_not_staged(self):
        feed = self.cdn / "latest.yml"
        feed.write_text(feed.read_text().replace("sha512: ", "sha512: AAAA", 1).replace("\nsha512: ", "\nsha512: AAAA"))
        self.assertIsNone(self.stage())
        self.assertIn("SHA-512", " ".join(self.logged))
        self.assertIsNone(u.install_staged(self.questlog, self.state, self.logged.append))
        self.assertEqual(u.installed_version(self.questlog), "0.1.34")

    def test_an_unfitting_version_is_reported_and_not_installed(self):
        installer = self.cdn / "questlog-setup-0.1.35.exe"
        # Rebuild the package with an Electron this A2Qlinux has not checked.
        build = Path(self.tmp.name) / "build2"
        make_app(build / "app", version="0.1.35", electron="45.0.0")
        (build / "nsis" / "$PLUGINSDIR").mkdir(parents=True)
        subprocess.run(["7z", "a", str(build / "nsis" / "$PLUGINSDIR" / "app-64.7z"), "."],
                       cwd=build / "app", check=True, capture_output=True)
        installer.unlink()
        subprocess.run(["7z", "a", "-t7z", str(installer), "$PLUGINSDIR"], cwd=build / "nsis",
                       check=True, capture_output=True)
        digest = base64.b64encode(hashlib.sha512(installer.read_bytes()).digest()).decode()
        text = (self.cdn / "latest.yml").read_text()
        text = "\n".join(
            f"{line.split('sha512:')[0]}sha512: {digest}" if "sha512:" in line else
            f"{line.split('size:')[0]}size: {installer.stat().st_size}" if "size:" in line else line
            for line in text.splitlines())
        (self.cdn / "latest.yml").write_text(text)
        state = self.stage()
        self.assertFalse(state["fits"])
        self.assertIn("Electron 45.0.0", self.notified[0])
        self.assertIsNone(u.install_staged(self.questlog, self.state, self.logged.append))
        self.assertEqual(u.installed_version(self.questlog), "0.1.34")

    def test_builtin_updater_is_switched_off(self):
        u.disable_builtin_updater(self.questlog, self.logged.append)
        self.assertFalse((self.questlog / "resources" / "app-update.yml").exists())
        self.assertEqual(len(self.logged), 1)


if __name__ == "__main__":
    unittest.main()
