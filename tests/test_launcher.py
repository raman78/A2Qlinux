import tempfile
import time
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


# An app id no Steam game has: the test's stand-in steam.exe carries it, so a
# real AION 2 running meanwhile is never touched (with the real id, the test
# ended the running game's own steam.exe on 8 November 2026).
FAKE_APPID = 999999901


class GameSteamHelperTest(unittest.TestCase):
    """Only a steam.exe carrying the game's app id is ended."""

    def setUp(self):
        self.saved_appid = q.APPID
        q.APPID = FAKE_APPID

    def tearDown(self):
        q.APPID = self.saved_appid

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


class QuestlogLaunchTest(unittest.TestCase):
    """Questlog's launch waits for the Wine session to end; the launcher still sees Questlog itself end."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.saved = q.shutil.which, q.os.environ.get("PATH")
        # Stand-ins for protontricks, wine and wineserver: protontricks runs the
        # command through the shell as the real one does; wine is "Questlog",
        # exiting with code 7; `wineserver -w` lasts until the session-end file appears.
        bin_dir = self.dir / "bin"
        bin_dir.mkdir()
        self.session_end = self.dir / "session-ended"
        scripts = {
            "protontricks": '#!/bin/bash\n[ "$1" = --no-background-wineserver ] || exit 90\nexec bash -c "$3"\n',
            "protontricks-launch": "#!/bin/bash\nexit 0\n",
            "wine": "#!/bin/bash\nexit 7\n",
            # Also ends when the test's folder is gone, so a failed test leaves nothing running.
            "wineserver": f'#!/bin/bash\nwhile [ ! -e {self.session_end} ] && [ -d {bin_dir} ]; do sleep 0.05; done\n',
        }
        for name, text in scripts.items():
            (bin_dir / name).write_text(text)
            (bin_dir / name).chmod(0o755)
        q.os.environ["PATH"] = f"{bin_dir}:{self.saved[1]}"
        q.shutil.which = lambda name: None if name == "systemd-run" else self.saved[0](name)
        self.exe = self.dir / "Questlog.exe"
        self.exe.touch()

        class Server:
            def environment_value(self):
                return "127.0.0.1:1:token"
        self.server = Server()

    def tearDown(self):
        q.shutil.which = self.saved[0]
        q.os.environ["PATH"] = self.saved[1]
        self.session_end.touch()
        self.tmp.cleanup()

    def test_questlogs_end_is_seen_while_its_launch_still_holds_the_session(self):
        launch = q.launch_questlog(self.exe, self.server, str(self.dir / "bin" / "protontricks-launch"),
                                   self.dir / "questlog.log")
        self.assertEqual(launch.wait(timeout=10), 7)
        self.assertIsNone(launch.process.poll())          # still waiting for the session to end
        self.session_end.touch()
        self.assertEqual(launch.process.wait(timeout=10), 0)

    def test_a_failed_call_counts_as_questlog_ended(self):
        (self.dir / "bin" / "protontricks").write_text("#!/bin/bash\nexit 3\n")
        launch = q.launch_questlog(self.exe, self.server, str(self.dir / "bin" / "protontricks-launch"),
                                   self.dir / "questlog.log")
        self.assertEqual(launch.wait(timeout=10), 3)

    def test_wait_gives_up_after_its_timeout(self):
        (self.dir / "bin" / "wine").write_text(f"#!/bin/bash\nsleep 5\n")
        launch = q.launch_questlog(self.exe, self.server, str(self.dir / "bin" / "protontricks-launch"),
                                   self.dir / "questlog.log")
        with self.assertRaises(q.subprocess.TimeoutExpired):
            launch.wait(timeout=0.3)
        self.session_end.touch()
        launch.process.kill()

    def test_command_and_its_scope(self):
        calls = []
        saved_popen = q.subprocess.Popen
        q.subprocess.Popen = lambda command, **kwargs: calls.append((command, kwargs)) or saved_popen(["true"])
        q.shutil.which = lambda name: "/usr/bin/systemd-run" if name == "systemd-run" else self.saved[0](name)
        try:
            q.launch_questlog(self.exe, self.server, str(self.dir / "bin" / "protontricks-launch"),
                              self.dir / "questlog.log", hidden=True)
            q.launch_questlog(self.exe, self.server, str(self.dir / "bin" / "protontricks-launch"),
                              self.dir / "questlog.log", hold_session=False)
        finally:
            q.subprocess.Popen = saved_popen
        held, handover = calls
        command, kwargs = held
        self.assertEqual(command[:3], ["systemd-run", "--user", "--scope"])
        tool = command[command.index("-c") - 2:]
        self.assertEqual(tool[0], str(self.dir / "bin" / "protontricks"))
        self.assertEqual(tool[1:3], ["--no-background-wineserver", "-c"])
        self.assertTrue(tool[3].startswith(f"wine {self.exe} --no-sandbox --hidden; echo $? > "))
        self.assertTrue(tool[3].endswith("; wineserver -w"))
        self.assertEqual(tool[4], str(q.APPID))
        self.assertEqual(kwargs["env"]["QUESTLOG_PROTON_BRIDGE"], "127.0.0.1:1:token")
        self.assertIn("wpcap=n", kwargs["env"]["WINEDLLOVERRIDES"])
        self.assertEqual(handover[0][0], str(self.dir / "bin" / "protontricks-launch"))
        self.assertNotIn("wineserver -w", " ".join(handover[0]))


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
    def __init__(self, stderr=b""):
        import io
        self.stdout = io.BytesIO(b"")      # ends at once: the pump records "dumpcap stopped"
        self.stderr = io.BytesIO(stderr) if isinstance(stderr, bytes) else stderr
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
        self.index = {"enp9s0": 2, "proton0": 5}

    def captures(self, wanted=(), stderr=b""):
        def start(dumpcap, name, address):
            process = FakeDumpcap(stderr)
            self.started.append((name, address, process))
            return process
        self.now = 0.0
        return q.Captures("dumpcap", self.server, wanted, {"packets": 0}, log=self.messages.append,
                          notify=self.notes.append, interfaces=lambda: dict(self.up), start=start,
                          game_addresses=lambda: set(self.game), index_of=self.index.get)

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

    def test_dumpcap_start_banner_is_not_repeated_but_its_errors_are_shown_above_ours(self):
        # What dumpcap 4.x writes on start (measured on lo), then a failure that arrives
        # late, so the "ended" line would come first if it did not wait for the relay.
        def stderr():
            yield b"Capturing on 'Tunnel: proton0'\n"
            yield b"File: -\n"
            time.sleep(0.2)
            yield b"dumpcap: The network adapter on which the capture was being done is no longer attached.\n"
        captures = self.captures(stderr=stderr())
        self.scan(captures)
        self.started[0][2].returncode = 1
        self.scan(captures)
        own = [m for m in self.messages if m.startswith("dumpcap on enp9s0:")]
        self.assertEqual(own, ["dumpcap on enp9s0: dumpcap: The network adapter on which the capture "
                               "was being done is no longer attached."])
        ended = next(i for i, m in enumerate(self.messages) if "ended:" in m)
        self.assertLess(self.messages.index(own[0]), ended)

    def test_dumpcap_counts_on_stop_are_passed_on(self):
        lines = []
        stream = [b"Capturing on 'Loopback: lo'\n", b"File: -\n", b"Packets captured: 0\n",
                  b"Packets received/dropped on interface 'Loopback: lo': 0/0 (0.0%)\n"]
        q.relay_dumpcap_messages("lo", stream, log=lines.append)
        self.assertEqual(lines, ["dumpcap on lo: Packets captured: 0",
                                 "dumpcap on lo: Packets received/dropped on interface 'Loopback: lo': 0/0 (0.0%)"])

    def test_failed_capture_is_retried_later_and_reported_only_once(self):
        captures = self.captures()
        self.scan(captures)
        self.started[0][2].returncode = 1
        self.scan(captures)                     # failure seen
        retry_at = self.now + q.CAPTURE_RETRY_EVERY
        while self.now + q.CAPTURE_SCAN_EVERY < retry_at:
            self.scan(captures)
        self.assertEqual(len(self.started), 1)  # not before the retry time
        self.scan(captures)                     # now at the retry time
        self.assertEqual(len(self.started), 2)  # tried again
        self.started[1][2].returncode = 1       # and fails again
        self.scan(captures)
        self.assertEqual(len(self.notes), 1)
        self.assertEqual(len([m for m in self.messages if "ended:" in m]), 1)

    def test_vpn_recreated_between_scans_is_captured_again_without_a_failure(self):
        # Proton VPN switching servers (8 November 2026): proton0 deleted and created again
        # within 0.6 s, same name, same address; dumpcap ends with the old interface.
        self.up["proton0"] = "10.2.0.2"
        captures = self.captures()
        self.scan(captures)
        old = [p for n, _, p in self.started if n == "proton0"][0]
        old.returncode = 0
        self.index["proton0"] = 6
        self.scan(captures)
        self.assertEqual([n for n, _, _ in self.started].count("proton0"), 2)
        self.assertIn("proton0", self.server.offered)
        self.assertEqual(self.notes, [])
        self.assertTrue(any("proton0 was created anew" in m for m in self.messages))

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

    def test_game_on_an_address_that_no_longer_exists_is_told_as_a_lost_network(self):
        # VPN switched off (8 November 2026): the game's connection stayed "established"
        # from 10.2.0.2 after proton0 had gone, and the game froze until it reconnected.
        self.up["proton0"] = "10.2.0.2"
        captures = self.captures()
        self.game.add("10.2.0.2")
        self.scan(captures)
        del self.up["proton0"]
        self.scan(captures)
        self.scan(captures)
        self.assertEqual(len(self.notes), 1)
        self.assertIn("lost its network", self.notes[0])
        self.assertFalse(any("does not capture on" in m for m in self.messages))

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


class LogFileTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "launcher.log"
        self.said = []

    def tearDown(self):
        self.tmp.cleanup()

    def test_lines_before_the_file_is_opened_are_written_once_it_is(self):
        logs = q.LogFile(say=self.said.append)
        logs.write("Settings: line 3 is wrong")
        self.assertFalse(self.path.exists())
        logs.open(self.path)
        logs.write("Capturing on eth0")
        lines = self.path.read_text().splitlines()
        self.assertEqual([line.split(" ", 2)[2] for line in lines], ["Settings: line 3 is wrong", "Capturing on eth0"])

    def test_the_log_is_capped_keeping_one_older_file(self):
        logs = q.LogFile(limit=200, say=self.said.append)
        logs.open(self.path)
        for n in range(30):
            logs.write(f"line {n:02d} " + "x" * 20)
        older = self.path.with_name("launcher.log.1")
        self.assertLessEqual(self.path.stat().st_size, 200)
        self.assertLessEqual(older.stat().st_size, 200)
        self.assertEqual(sorted(p.name for p in self.path.parent.iterdir()), ["launcher.log", "launcher.log.1"])
        self.assertIn("line 29", self.path.read_text())

    def test_an_unwritable_log_is_said_once_and_the_launcher_goes_on(self):
        logs = q.LogFile(say=self.said.append)
        logs.open(Path(self.tmp.name) / "missing" / "launcher.log")
        logs.write("one")
        logs.write("two")
        self.assertEqual(len(self.said), 1)
        self.assertIn("only in this window", self.said[0])
