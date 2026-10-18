import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import questlog_desktop as d


class LauncherPidTest(unittest.TestCase):
    """The desktop entry signals only a process that really is questlog_start.py."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.saved_lock = d.LOCK
        d.LOCK = Path(self.tmp.name) / ".lock"

    def tearDown(self):
        d.LOCK = self.saved_lock
        self.tmp.cleanup()

    def test_pid_of_a_running_launcher(self):
        launcher = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)", "questlog_start.py"])
        try:
            d.LOCK.write_text(f"{launcher.pid}\n")
            self.assertEqual(d.launcher_pid(), launcher.pid)
        finally:
            launcher.kill()
            launcher.wait()

    def test_pid_of_another_program_is_refused(self):
        d.LOCK.write_text(f"{os.getpid()}\n")       # this test runner, not questlog_start.py
        self.assertIsNone(d.launcher_pid())

    def test_empty_or_missing_lock_gives_none(self):
        self.assertIsNone(d.launcher_pid())
        d.LOCK.write_text("")                        # what launchers before the PID was written leave
        self.assertIsNone(d.launcher_pid())


if __name__ == "__main__":
    unittest.main()
