import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

from a2qlinux import desktop as d


class LauncherPidTest(unittest.TestCase):
    """The desktop entry signals only a process that really is the launcher."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.saved_lock = d.LOCK
        d.LOCK = Path(self.tmp.name) / ".lock"

    def tearDown(self):
        d.LOCK = self.saved_lock
        self.tmp.cleanup()

    def test_pid_of_a_running_launcher(self):
        launcher = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)", "-m", "a2qlinux.launcher"])
        try:
            # Until the child has exec'd, its /proc cmdline is still this runner's.
            deadline = time.monotonic() + 2
            while (b"a2qlinux.launcher" not in Path(f"/proc/{launcher.pid}/cmdline").read_bytes()
                   and time.monotonic() < deadline):
                time.sleep(0.01)
            d.LOCK.write_text(f"{launcher.pid}\n")
            self.assertEqual(d.launcher_pid(), launcher.pid)
        finally:
            launcher.kill()
            launcher.wait()

    def test_pid_of_another_program_is_refused(self):
        d.LOCK.write_text(f"{os.getpid()}\n")       # this test runner, not the launcher
        self.assertIsNone(d.launcher_pid())

    def test_empty_or_missing_lock_gives_none(self):
        self.assertIsNone(d.launcher_pid())
        d.LOCK.write_text("")                        # what launchers before the PID was written leave
        self.assertIsNone(d.launcher_pid())


class TerminalTest(unittest.TestCase):
    """The status window opens in the first terminal found, with that terminal's own option."""

    def which(self, *installed):
        return lambda name: f"/usr/bin/{name}" if name in installed else None

    def test_konsole_first_when_several_are_installed(self):
        command = d.terminal_command(["bash", "-c", "x"], self.which("xterm", "gnome-terminal", "konsole"))
        self.assertEqual(command, ["/usr/bin/konsole", "-e", "bash", "-c", "x"])

    def test_each_terminal_gets_its_own_option(self):
        for name, option in d.TERMINALS:
            with self.subTest(name):
                self.assertEqual(d.terminal_command(["prog", "arg"], self.which(name)),
                                 [f"/usr/bin/{name}", *option, "prog", "arg"])

    def test_gnome_terminal_and_ptyxis_take_the_program_after_a_double_dash(self):
        self.assertEqual(d.terminal_command(["prog"], self.which("ptyxis"))[1:], ["--", "prog"])
        self.assertEqual(d.terminal_command(["prog"], self.which("gnome-terminal"))[1:], ["--", "prog"])

    def test_none_without_a_terminal(self):
        self.assertIsNone(d.terminal_command(["prog"], self.which()))

    def test_without_a_terminal_the_user_is_told_which_to_install(self):
        import a2qlinux.setup_desktop as setup
        saved = (d.terminal_command, d.notify, d.launcher_running, setup.refresh_entries)
        told = []
        d.terminal_command = lambda program: None
        d.notify = told.append
        d.launcher_running = lambda: False
        setup.refresh_entries = lambda log: []
        try:
            self.assertEqual(d.main(), 1)
        finally:
            d.terminal_command, d.notify, d.launcher_running, setup.refresh_entries = saved
        self.assertEqual(len(told), 1)
        self.assertIn("konsole", told[0])
        self.assertIn("xterm", told[0])


if __name__ == "__main__":
    unittest.main()
