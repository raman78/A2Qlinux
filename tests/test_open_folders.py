import unittest

from a2qlinux import open_folders as f


class FakeCtl:
    """Stand-in for questlog_ctl.exe folder-handler: a registry with one value, and the calls made."""

    def __init__(self, value=None, fail=False):
        self.value, self.fail, self.calls = value, fail, []

    def __call__(self, action):
        self.calls.append(action)
        if self.fail:
            raise RuntimeError("questlog_ctl.exe did not answer within 120 s")
        ours = self.value == "ours"
        if action == "status":
            return ("absent", "absent: …") if self.value is None else (("ours", "ours: …") if ours
                                                                       else ("other", "other: …"))
        if action == "set":
            if self.value is None:
                self.value = "ours"
                return "set", "set: …"
            return ("ours", "ours: …") if ours else ("other", "other: …")
        if action == "remove":
            if ours:
                self.value = None
                return "removed", "removed: …"
            return ("absent", "absent: …") if self.value is None else ("other", "other: …")
        raise AssertionError(action)


class SetupStepTest(unittest.TestCase):
    def step(self, ctl, want=None, answer="", interactive=True):
        self.asked, self.logged = [], []

        def ask(prompt):
            self.asked.append(prompt)
            return answer
        return f.setup_step(want, ask, interactive, log=self.logged.append, ctl=ctl)

    def test_absent_asks_and_sets_on_enter(self):
        ctl = FakeCtl()
        self.assertIsNone(self.step(ctl))
        self.assertEqual(len(self.asked), 1)
        self.assertEqual(ctl.calls, ["status", "set"])
        self.assertEqual(ctl.value, "ours")

    def test_absent_refused_leaves_the_prefix_alone(self):
        ctl = FakeCtl()
        self.assertIsNone(self.step(ctl, answer="n"))
        self.assertEqual(ctl.calls, ["status"])
        self.assertIsNone(ctl.value)
        self.assertIn("--open-folders", self.logged[-1])

    def test_without_a_terminal_only_names_the_option(self):
        ctl = FakeCtl()
        self.assertIsNone(self.step(ctl, interactive=False))
        self.assertEqual((self.asked, ctl.calls), ([], ["status"]))
        self.assertIn("--open-folders", self.logged[-1])

    def test_option_sets_up_without_asking(self):
        ctl = FakeCtl()
        self.assertIsNone(self.step(ctl, want=True, interactive=False))
        self.assertEqual((self.asked, ctl.calls, ctl.value), ([], ["status", "set"], "ours"))

    def test_set_up_already_is_not_asked_again(self):
        ctl = FakeCtl("ours")
        self.assertIsNone(self.step(ctl))
        self.assertEqual((self.asked, ctl.calls), ([], ["status"]))

    def test_someone_elses_command_is_never_replaced(self):
        for want in (None, True):
            ctl = FakeCtl("someone-else.exe %1")
            self.assertIsNone(self.step(ctl, want=want))
            self.assertEqual((self.asked, ctl.calls, ctl.value), ([], ["status"], "someone-else.exe %1"))
            self.assertIn("leaves it", self.logged[-1])

    def test_removal(self):
        ctl = FakeCtl("ours")
        self.assertIsNone(self.step(ctl, want=False))
        self.assertEqual((ctl.calls, ctl.value), (["remove"], None))
        ctl = FakeCtl("someone-else.exe %1")
        self.assertIsNone(self.step(ctl, want=False))
        self.assertEqual(ctl.value, "someone-else.exe %1")

    def test_failure_is_a_note_with_the_reason(self):
        problem = self.step(FakeCtl(fail=True))
        self.assertIn("did not answer within 120 s", problem)
        self.assertIn("Open Folder", problem)


class OutcomeTest(unittest.TestCase):
    def test_reads_the_first_outcome_line(self):
        out = "some wine noise\nset: folders now open through winebrowser.exe (…).\n"
        self.assertEqual(f.outcome(out), ("set", "set: folders now open through winebrowser.exe (…)."))

    def test_no_outcome(self):
        self.assertEqual(f.outcome("usage: questlog_ctl.exe …\n"), (None, "usage: questlog_ctl.exe …"))

    def test_run_ctl_reports_a_ctl_without_an_answer(self):
        import subprocess
        from unittest import mock
        done = subprocess.CompletedProcess([], 1, stdout="", stderr="wine: could not load\nprotontricks: app not found\n")
        with mock.patch.object(f.shutil, "which", return_value="/usr/bin/protontricks-launch"), \
                mock.patch.object(f.subprocess, "run", return_value=done), \
                mock.patch("a2qlinux.launcher.CTL") as ctl:
            ctl.is_file.return_value = True
            with self.assertRaises(RuntimeError) as caught:
                f.run_ctl("status")
        self.assertIn("app not found", str(caught.exception))
        self.assertIn("exit code 1", str(caught.exception))


# As Wine saves them in system.reg (copied from a game prefix).
SYSTEM_REG = r"""WINE REGISTRY Version 2
;; All keys relative to \\Machine

[Software\\Classes\\folder\\shell\\open\\ddeexec] 1785139151
@="[ViewFolder(%l, %I, %S)]"

{handler}[Software\\Classes\\ftp] 1785139151
"URL Protocol"=""
"""
OURS = r"""[Software\\Classes\\folder\\shell\\explore\\command] 1794570874
#time=1dd7365c0021084
@="\"C:\\windows\\system32\\winebrowser.exe\" \"%1\""

"""
OTHER = r"""[Software\\Classes\\folder\\shell\\explore\\command] 1
@="other.exe %1"

"""
NO_COMMAND = r"""[Software\\Classes\\folder\\shell\\explore\\command] 1

"""


class RegistryStateTest(unittest.TestCase):
    def state(self, handler):
        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "system.reg"
            path.write_text(SYSTEM_REG.format(handler=handler))
            return f.registry_state(path)

    def test_absent(self):
        self.assertEqual(self.state(""), ("absent", None))

    def test_ours_as_wine_saves_it(self):
        self.assertEqual(self.state(OURS), ("ours", f.HANDLER_VALUE))

    def test_someone_elses(self):
        self.assertEqual(self.state(OTHER), ("other", "other.exe %1"))
        self.assertEqual(self.state(NO_COMMAND), ("other", None))

    def test_the_value_matches_questlog_ctl(self):
        from pathlib import Path
        source = (Path(__file__).resolve().parent.parent / "bridge" / "questlog_ctl.c").read_text()
        line = next(l for l in source.splitlines() if l.startswith("#define HANDLER_VALUE"))
        literal = line.split(" L", 1)[1].strip()[1:-1]
        self.assertEqual(literal.replace('\\"', '"').replace("\\\\", "\\"), f.HANDLER_VALUE)


if __name__ == "__main__":
    unittest.main()
