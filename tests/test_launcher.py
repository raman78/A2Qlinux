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


class GameSteamHelperTest(unittest.TestCase):
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
            self.assertEqual(q.end_game_steam_helper("in a test"), 1)
            self.assertIsNotNone(ours.wait(timeout=5))
            self.assertIsNone(other.poll())
        finally:
            for process in (ours, other):
                if process.poll() is None:
                    process.kill()
                    process.wait()


# Process tables shaped like those seen with the real game (20 October 2026):
# {pid: (parent, kernel name, argv[0])}.
STEAM_CLIENT = {1215: (1, "systemd", "/usr/lib/systemd/systemd"),
                5000: (1215, "steam", "/home/u/.local/share/Steam/ubuntu12_32/steam")}
GAME_LAUNCH = {   # reaper -> container -> Proton's script -> steam.exe
    83705: (5000, "reaper", "/home/u/.local/share/Steam/ubuntu12_32/reaper"),
    83709: (83705, "srt-bwrap", "/home/u/Games/steamapps/common/SteamLinuxRuntime_4/.../srt-bwrap"),
    83778: (83709, "pv-adverb", "/usr/lib/pressure-vessel/from-host/libexec/steam-runtime-tools-0/pv-adverb"),
    83811: (83778, "python3", "python3"),
    83812: (83811, "steam.exe", "c:\\windows\\system32\\steam.exe"),
}
QUESTLOG_LAUNCH = {   # protontricks-launch -> container, holding the session's wineserver and Questlog
    80900: (1215, "protontricks-la", "/usr/bin/python"),
    80960: (80900, "pv-adverb", "/usr/lib/pressure-vessel/from-host/libexec/steam-runtime-tools-0/pv-adverb"),
    81141: (80960, "wineserver", "/run/host/usr/share/steam/compatibilitytools.d/proton-cachyos-slr/files/bin/wineserver"),
    81148: (80960, "winedevice.exe", "C:\\windows\\system32\\winedevice.exe"),
    81195: (80960, "CrBrowserMain", "Z:\\home\\u\\Games\\Questlog\\Questlog.exe"),
}


class GameLaunchStateTest(unittest.TestCase):
    """Whose launch holds the Wine session decides between ending steam.exe and restarting Questlog."""

    def test_game_joined_questlogs_session_only_steam_exe_left(self):
        table = {**STEAM_CLIENT, **GAME_LAUNCH, **QUESTLOG_LAUNCH}
        self.assertEqual(q.game_launch_state(table, {83812}), ("release", {83812}))

    def test_game_programs_still_ending(self):
        table = {**STEAM_CLIENT, **GAME_LAUNCH, **QUESTLOG_LAUNCH,
                 84458: (83778, "EpicWebHelper.e", "Z:/home/u/Games/steamapps/common/AION2/Engine/EpicWebHelper.exe")}
        self.assertEqual(q.game_launch_state(table, {83812}), ("wait", ["epicwebhelper.exe"]))

    def test_session_started_by_the_game(self):
        table = {**STEAM_CLIENT, **GAME_LAUNCH,
                 83900: (83778, "wineserver", "/run/host/usr/share/steam/.../bin/wineserver"),
                 83901: (83778, "explorer.exe", "C:\\windows\\system32\\explorer.exe"),
                 81195: (80960, "CrBrowserMain", "Z:\\home\\u\\Games\\Questlog\\Questlog.exe")}
        state, _ = q.game_launch_state(table, {83812})
        self.assertEqual(state, "restart")

    def test_steam_exe_without_a_reaper_is_not_ended(self):
        table = {**STEAM_CLIENT, 83812: (1215, "steam.exe", "c:\\windows\\system32\\steam.exe")}
        state, _ = q.game_launch_state(table, {83812})
        self.assertEqual(state, "restart")

    def test_no_steam_exe_left(self):
        self.assertEqual(q.game_launch_state({**STEAM_CLIENT, **QUESTLOG_LAUNCH}, set()), ("free", None))


class AfterGameTest(unittest.TestCase):
    def test_steam_exe_is_ended_once_it_has_been_alone_for_the_settle_time(self):
        after = q.AfterGame(exited_at=100.0, settle=2)
        self.assertIsNone(after.next("wait", 100.5))
        self.assertIsNone(after.next("release", 101.0))
        self.assertIsNone(after.next("release", 102.5))
        self.assertEqual(after.next("release", 103.0), "release")

    def test_settle_time_starts_again_when_other_programs_reappear(self):
        after = q.AfterGame(exited_at=100.0, settle=2)
        after.next("release", 101.0)
        after.next("wait", 102.0)
        self.assertIsNone(after.next("release", 103.5))
        self.assertEqual(after.next("release", 105.5), "release")

    def test_restart_waits_until_the_last_data_is_saved(self):
        after = q.AfterGame(exited_at=100.0, save_wait=10.5)
        self.assertIsNone(after.next("restart", 105.0, last_data=99.0))
        self.assertEqual(after.next("restart", 109.5, last_data=99.0), "restart")

    def test_restart_at_once_without_recent_data(self):
        after = q.AfterGame(exited_at=100.0, save_wait=10.5)
        self.assertEqual(after.next("restart", 100.0, last_data=50.0), "restart")
        self.assertEqual(q.AfterGame(exited_at=100.0).next("restart", 100.0), "restart")

    def test_free_needs_nothing(self):
        self.assertEqual(q.AfterGame(exited_at=100.0).next("free", 100.0), "free")


class ReleaseSteamAfterQuestlogTest(unittest.TestCase):
    """After Questlog is ended with the game gone, a steam.exe left over is ended once the session closes."""

    def setUp(self):
        self.saved = q.game_processes, q.wine_session_running, q.end_game_steam_helper
        self.ended = []
        q.end_game_steam_helper = lambda why, pids=None: self.ended.append(why) or 1

    def tearDown(self):
        q.game_processes, q.wine_session_running, q.end_game_steam_helper = self.saved

    def fake(self, game, steam_exe, session):
        q.game_processes = lambda appid, names: {"aion2.exe": game, "steam.exe": steam_exe}
        q.wine_session_running = lambda prefix: session

    def test_left_over_steam_exe_is_ended_once_the_session_is_gone(self):
        self.fake(game=set(), steam_exe={83812}, session=False)
        self.assertTrue(q.release_steam_after_questlog(Path("/pfx")))
        self.assertEqual(len(self.ended), 1)

    def test_nothing_while_the_game_runs(self):
        self.fake(game={83816}, steam_exe={83812}, session=False)
        self.assertTrue(q.release_steam_after_questlog(Path("/pfx")))
        self.assertEqual(self.ended, [])

    def test_no_wait_without_a_steam_exe(self):
        self.fake(game=set(), steam_exe=set(), session=True)
        started = q.time.monotonic()
        self.assertTrue(q.release_steam_after_questlog(Path("/pfx")))
        self.assertLess(q.time.monotonic() - started, 0.5)
        self.assertEqual(self.ended, [])


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


class GamePrefixTest(unittest.TestCase):
    """Without a running game, the prefix is found through whichever native Steam installation exists."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.home = Path(self.tmp.name)
        self.saved = (q.game_processes, q.FLATPAK_STEAM)
        q.game_processes = lambda appid, names: {name: set() for name in names}   # no game running
        q.FLATPAK_STEAM = self.home / "flatpak-steam"

    def tearDown(self):
        q.game_processes, q.FLATPAK_STEAM = self.saved
        self.tmp.cleanup()

    def steam(self, folder, library):
        """A Steam installation in `folder` whose library list names `library`, which holds the game's prefix."""
        (folder / "steamapps").mkdir(parents=True)
        (folder / "steamapps" / "libraryfolders.vdf").write_text(f'"libraryfolders"\n{{\n "0"\n {{\n  "path"  "{library}"\n }}\n}}\n')
        prefix = library / "steamapps" / "compatdata" / str(q.APPID) / "pfx"
        (prefix / "drive_c").mkdir(parents=True)
        return prefix

    def test_installation_outside_local_share_found_through_valves_link(self):
        installed = self.home / ".steam" / "debian-installation"
        prefix = self.steam(installed, self.home / "games")
        (self.home / ".steam" / "steam").symlink_to(installed)
        roots = q.steam_roots(self.home)
        self.assertEqual(roots, [installed.resolve()])
        self.assertEqual(q.game_prefix(q.APPID, roots), prefix)

    def test_one_installation_behind_several_links_is_listed_once(self):
        installed = self.home / ".local" / "share" / "Steam"
        installed.mkdir(parents=True)
        (self.home / ".steam").mkdir()
        (self.home / ".steam" / "steam").symlink_to(installed)
        (self.home / ".steam" / "root").symlink_to(installed)
        self.assertEqual(q.steam_roots(self.home), [installed.resolve()])

    def test_only_a_flatpak_steam_is_named_as_such(self):
        q.FLATPAK_STEAM.mkdir()
        with self.assertRaisesRegex(RuntimeError, "Flatpak"):
            q.game_prefix(q.APPID, [])

    def test_missing_prefix_names_the_lists_looked_in(self):
        installed = self.home / "Steam"
        (installed / "steamapps").mkdir(parents=True)
        with self.assertRaisesRegex(RuntimeError, "libraryfolders.vdf.*Start the game once"):
            q.game_prefix(q.APPID, [installed])


if __name__ == "__main__":
    unittest.main()


class FakeDumpcap:
    def __init__(self):
        import io
        self.stdout = io.BytesIO(b"")      # ends at once: the pump records "dumpcap stopped"
        self.returncode = None
        self.terminated = False

    def poll(self):
        return self.returncode

    def terminate(self):
        self.terminated = True
        self.returncode = -15

    def wait(self, timeout=None):
        return self.returncode


class FakeServer:
    def __init__(self):
        self.offered = {}

    def add_interface(self, name, address):
        self.offered[name] = address

    def remove_interface(self, name):
        self.offered.pop(name, None)

    def publish(self, name, header, record):
        pass


class CapturesTest(unittest.TestCase):
    def setUp(self):
        self.up = {"enp9s0": "10.0.4.90"}
        self.started = []
        self.messages, self.notes = [], []
        self.server = FakeServer()
        self.game = set()

    def captures(self, wanted=()):
        def start(dumpcap, name, address):
            process = FakeDumpcap()
            self.started.append((name, address, process))
            return process
        self.now = 0.0
        return q.Captures("dumpcap", self.server, wanted, {"packets": 0}, log=self.messages.append,
                          notify=self.notes.append, interfaces=lambda: dict(self.up), start=start,
                          game_addresses=lambda: set(self.game))

    def scan(self, captures):
        self.now += q.CAPTURE_SCAN_EVERY
        captures.scan(self.now)

    def test_every_interface_is_captured_and_offered(self):
        self.up["proton0"] = "10.2.0.2"
        captures = self.captures()
        self.scan(captures)
        self.assertEqual(self.server.offered, {"enp9s0": "10.0.4.90", "proton0": "10.2.0.2"})
        self.assertEqual(sorted(n for n, _, _ in self.started), ["enp9s0", "proton0"])

    def test_vpn_coming_up_and_going_down_is_followed(self):
        captures = self.captures()
        self.scan(captures)
        self.up["proton0"] = "10.2.0.2"
        self.scan(captures)
        self.assertIn("proton0", self.server.offered)
        vpn = self.started[-1][2]
        del self.up["proton0"]
        self.scan(captures)
        self.assertNotIn("proton0", self.server.offered)
        self.assertTrue(vpn.terminated)
        self.assertTrue(any("proton0 is gone" in m for m in self.messages))
        self.assertEqual(self.notes, [])        # a VPN switched off is no failure

    def test_address_change_restarts_the_capture(self):
        captures = self.captures()
        self.scan(captures)
        self.up["enp9s0"] = "10.0.4.91"
        self.scan(captures)
        self.assertEqual(self.server.offered, {"enp9s0": "10.0.4.91"})
        self.assertEqual([a for _, a, _ in self.started], ["10.0.4.90", "10.0.4.91"])

    def test_failed_dumpcap_is_reported_once_and_not_restarted_in_a_loop(self):
        captures = self.captures()
        self.scan(captures)
        self.started[0][2].returncode = 1
        for _ in range(3):
            self.scan(captures)
        self.assertEqual(len(self.started), 1)
        self.assertEqual(len(self.notes), 1)
        self.assertIn("enp9s0", self.notes[0])
        self.assertNotIn("enp9s0", self.server.offered)
        self.assertTrue(any("a2qlinux-setup" in m for m in self.messages))
        self.up["enp9s0"] = "10.0.4.91"         # a new address: tried again
        self.scan(captures)
        self.assertEqual(len(self.started), 2)

    def test_wanted_limits_capture_and_a_missing_one_is_told_once(self):
        self.up["proton0"] = "10.2.0.2"
        captures = self.captures(wanted=("proton0", "wg1"))
        self.scan(captures)
        self.scan(captures)
        self.assertEqual(self.server.offered, {"proton0": "10.2.0.2"})
        self.assertEqual(len([m for m in self.messages if "wg1" in m]), 1)

    def test_no_interface_is_told_once_and_capture_starts_later(self):
        self.up.clear()
        captures = self.captures()
        self.scan(captures)
        self.scan(captures)
        self.assertEqual(len([m for m in self.messages if "No network interface" in m]), 1)
        self.up["enp9s0"] = "10.0.4.90"
        self.scan(captures)
        self.assertEqual(self.server.offered, {"enp9s0": "10.0.4.90"})

    def test_scan_waits_between_looks(self):
        captures = self.captures()
        captures.scan(10.0)
        self.up["proton0"] = "10.2.0.2"
        captures.scan(10.5)
        self.assertNotIn("proton0", self.server.offered)
        captures.scan(10.0 + q.CAPTURE_SCAN_EVERY)
        self.assertIn("proton0", self.server.offered)

    def test_game_on_an_uncaptured_address_is_reported_once_per_occurrence(self):
        self.up["proton0"] = "10.2.0.2"
        captures = self.captures(wanted=("enp9s0",))
        self.game.add("10.2.0.2")
        self.scan(captures)
        self.scan(captures)
        self.assertEqual(len(self.notes), 1)
        self.assertIn("10.2.0.2", self.notes[0])
        self.assertTrue(any("'interface' limits capture to enp9s0" in m for m in self.messages))
        self.game.clear()
        self.scan(captures)
        self.game.add("10.2.0.2")                 # back again later: told again
        self.scan(captures)
        self.assertEqual(len(self.notes), 2)

    def test_game_on_a_captured_address_is_quiet(self):
        self.up["proton0"] = "10.2.0.2"
        captures = self.captures()
        self.game.add("10.2.0.2")
        self.scan(captures)
        self.assertEqual(self.notes, [])


class GameConnectionAddressesTest(unittest.TestCase):
    def test_reads_established_connections_to_the_game_port(self):
        table = ("  sl  local_address rem_address   st tx_queue rx_queue tr tm->when retrnsmt   uid\n"
                 # 10.2.0.2:35886 -> 193.202.112.131:13328, ESTABLISHED
                 "   0: 0200020A:8C2E 8370CAC1:3410 01 00000000:00000000 00:00000000 00000000  1000\n"
                 # 10.0.4.90 -> :13328, CLOSE_WAIT: not counted
                 "   1: 5A04000A:8C2F 8370CAC1:3410 08 00000000:00000000 00:00000000 00000000  1000\n"
                 # 10.0.4.90 -> :443, ESTABLISHED: another port
                 "   2: 5A04000A:8C30 8370CAC1:01BB 01 00000000:00000000 00:00000000 00000000  1000\n")
        with tempfile.NamedTemporaryFile("w", suffix="tcp") as f:
            f.write(table)
            f.flush()
            self.assertEqual(q.game_connection_addresses(f.name), {"10.2.0.2"})

    def test_this_machine_now(self):
        q.game_connection_addresses()             # the real table parses (whatever it holds)


class PumpRecordsTest(unittest.TestCase):
    def test_link_type_questlog_cannot_read_is_reported(self):
        import io
        import struct
        messages = []
        for linktype, told in ((101, False), (9, True)):
            header = struct.pack("<IHHiIII", 0xA1B2C3D4, 2, 4, 0, 0, 262144, linktype)
            capture = {"error": None}
            q.pump_records("ppp0", io.BytesIO(header), FakeServer(), {"packets": 0}, capture, messages.append)
            self.assertEqual(any("link type 9" in m for m in messages), told)
            self.assertEqual(capture["error"], "dumpcap stopped")
