import tempfile
import unittest
from pathlib import Path

from a2qlinux import launcher as q


class InstallBridgeDllTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.prefix = Path(self.tmp.name)
        self.target = self.prefix / "drive_c" / "windows" / "system32" / "Npcap" / "wpcap.dll"
        self.target.parent.parent.mkdir(parents=True)
        # A stand-in for the built DLL, so the tests do not depend on bridge/build.sh having run.
        self.ours = b"MZ current build " + q.BRIDGE_SIGNATURE + b" ..."
        self.saved_dll = q.BRIDGE_DLL
        q.BRIDGE_DLL = Path(self.tmp.name) / "built-wpcap.dll"
        q.BRIDGE_DLL.write_bytes(self.ours)

    def tearDown(self):
        q.BRIDGE_DLL = self.saved_dll
        self.tmp.cleanup()

    def test_installs_when_missing(self):
        q.install_bridge_dll(self.prefix)
        self.assertEqual(self.target.read_bytes(), self.ours)

    def test_replaces_empty_marker(self):
        self.target.parent.mkdir()
        self.target.touch()
        q.install_bridge_dll(self.prefix)
        self.assertEqual(self.target.read_bytes(), self.ours)

    def test_replaces_older_build_of_ours(self):
        self.target.parent.mkdir()
        self.target.write_bytes(b"MZ old build " + q.BRIDGE_SIGNATURE + b" ...")
        q.install_bridge_dll(self.prefix)
        self.assertEqual(self.target.read_bytes(), self.ours)

    def test_leaves_foreign_dll_alone(self):
        self.target.parent.mkdir()
        self.target.write_bytes(b"MZ real npcap")
        with self.assertRaises(RuntimeError):
            q.install_bridge_dll(self.prefix)
        self.assertEqual(self.target.read_bytes(), b"MZ real npcap")


class QuitControlTest(unittest.TestCase):
    def setUp(self):
        self.control = q.QuitControl(save_wait=10.5)

    def test_without_game_data_quit_is_immediate(self):
        self.assertEqual(self.control.handle("quit", 100.0, last_data=None), ["tray-off"])
        self.assertTrue(self.control.due(100.0))

    def test_old_game_data_does_not_delay_the_quit(self):
        self.assertEqual(self.control.handle("quit", 100.0, last_data=80.0), ["tray-off"])
        self.assertTrue(self.control.due(100.0))

    def test_recent_game_data_hides_now_and_ends_after_the_save_wait(self):
        self.assertEqual(self.control.handle("quit", 100.0, last_data=99.0), ["tray-off", "close-window"])
        self.assertFalse(self.control.due(109.4))
        self.assertTrue(self.control.due(109.5))

    def test_second_quit_changes_nothing(self):
        self.control.handle("quit", 100.0, last_data=99.0)
        self.assertEqual(self.control.handle("quit", 105.0, last_data=104.0), [])
        self.assertTrue(self.control.due(109.5))

    def test_open_while_quitting_calls_the_quit_off_and_shows_the_window(self):
        self.control.handle("quit", 100.0, last_data=99.0)
        self.assertEqual(self.control.handle("open", 103.0), ["tray-on", "show-window"])
        self.assertFalse(self.control.due(200.0))

    def test_keep_while_quitting_calls_the_quit_off_without_a_window(self):
        self.control.handle("quit", 100.0, last_data=99.0)
        self.assertEqual(self.control.handle("keep", 103.0), ["tray-on"])
        self.assertFalse(self.control.due(200.0))

    def test_open_and_keep_when_running(self):
        self.assertEqual(self.control.handle("open", 1.0), ["show-window"])
        self.assertEqual(self.control.handle("keep", 1.0), [])
        self.assertFalse(self.control.due(100.0))

    def test_unknown_request_is_refused(self):
        with self.assertRaises(ValueError):
            self.control.handle("reboot", 1.0)


class RequestsTest(unittest.TestCase):
    def test_take_returns_in_order_and_empties(self):
        requests = q.Requests()
        requests.put("quit")
        requests.put("open")
        self.assertEqual(requests.take(), ["quit", "open"])
        self.assertEqual(requests.take(), [])


class SessionLockTest(unittest.TestCase):
    def test_lock_holds_our_pid_and_refuses_a_second_launcher(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            (directory / ".lock").write_text("99999999\nleftover from an older run\n")
            fd = q.session_lock(directory)
            try:
                self.assertEqual((directory / ".lock").read_text(), f"{q.os.getpid()}\n")
                child = q.subprocess.run([q.sys.executable, "-c",
                                          "import sys; from a2qlinux import launcher as q; from pathlib import Path\n"
                                          "try: q.session_lock(Path(sys.argv[1]))\n"
                                          "except RuntimeError: sys.exit(3)", tmp], cwd=Path(q.__file__).parents[1])
                self.assertEqual(child.returncode, 3)
            finally:
                q.os.close(fd)


class OrphanedSteamHelperTest(unittest.TestCase):
    """Only a steam.exe carrying the game's app id is ended."""

    def test_ends_the_games_steam_exe_and_nothing_else(self):
        def start(appid):
            return q.subprocess.Popen(["bash", "-c", "exec -a 'c:\\windows\\system32\\steam.exe' sleep 30"],
                                      env={"SteamAppId": appid, "PATH": "/usr/bin:/bin"})
        ours, other = start(str(q.APPID)), start("12345")
        try:
            for _ in range(50):                           # until both have exec'd under the new name
                if ours.pid in q.game_processes(q.APPID, ["steam.exe"])["steam.exe"]:
                    break
                q.time.sleep(0.02)
            self.assertEqual(q.end_orphaned_steam_helper(), 1)
            self.assertIsNotNone(ours.wait(timeout=5))
            self.assertIsNone(other.poll())
        finally:
            for process in (ours, other):
                if process.poll() is None:
                    process.kill()
                    process.wait()


class WineSessionRunningTest(unittest.TestCase):
    """A process whose executable is named wineserver, as the kernel reports it, with WINEPREFIX set."""

    def test_finds_a_wineserver_by_prefix(self):
        import shutil
        with tempfile.TemporaryDirectory() as tmp:
            fake = Path(tmp) / "wineserver"
            shutil.copy(shutil.which("sleep"), fake)
            prefix = Path(tmp) / "pfx"
            prefix.mkdir()
            server = q.subprocess.Popen([str(fake), "30"], env={"WINEPREFIX": str(prefix) + "/"})
            try:
                for _ in range(50):                       # until the kernel shows the new name
                    if q._read(f"/proc/{server.pid}/comm").strip() == "wineserver":
                        break
                    q.time.sleep(0.02)
                self.assertTrue(q.wine_session_running(prefix))
                self.assertFalse(q.wine_session_running(Path(tmp)))
            finally:
                server.kill()
                server.wait()
            self.assertFalse(q.wine_session_running(prefix))


if __name__ == "__main__":
    unittest.main()
