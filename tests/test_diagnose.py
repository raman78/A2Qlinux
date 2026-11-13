import tempfile
import unittest
import urllib.parse
from pathlib import Path

from a2qlinux import diagnose as d

LOCALCONFIG = '''"UserLocalConfigStore"
{
	"Software"
	{
		"Valve"
		{
			"Steam"
			{
				"Apps"
				{
					"570"
					{
						"LaunchOptions"		"-novid"
					}
					"3393110"
					{
						"LaunchOptions"		"PROTON_FSR4_UPGRADE=1 %s %%command%%"
					}
				}
			}
		}
	}
}
'''


class LaunchOptionTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.ours = self.root / "bin" / "a2qlinux-steam"
        self.ours.parent.mkdir()
        self.ours.write_text("#!/bin/sh\n")

    def tearDown(self):
        self.tmp.cleanup()

    def account(self, number, option_for_game):
        config = self.root / "Steam" / "userdata" / str(number) / "config"
        config.mkdir(parents=True)
        (config / "localconfig.vdf").write_text(LOCALCONFIG % option_for_game)

    def test_the_games_option_is_read_from_each_account_not_another_games(self):
        self.account(111, str(self.ours))
        found = d.launch_options([self.root / "Steam"], 3393110)
        self.assertEqual([(a.name, o) for a, o in found],
                         [("111", f"PROTON_FSR4_UPGRADE=1 {self.ours} %command%")])

    def test_judgements(self):
        ours = str(self.ours)
        cases = {
            None: d.NOTE,
            "-novid %command%": d.NOTE,
            f"{ours}": d.PROBLEM,                                  # no %command%: the game never starts
            "a2qlinux-steam %command%": d.PROBLEM,                 # Steam cannot find it without a folder
            f"{self.root}/gone/a2qlinux-steam %command%": d.PROBLEM,
            f"PROTON_FSR4_UPGRADE=1 {ours} %command%": d.OK,       # rey's, 10 November 2026
        }
        for option, level in cases.items():
            with self.subTest(option=option):
                self.assertEqual(d.judge_launch_option(option, ours)[0], level)


class AnonymiserTest(unittest.TestCase):
    def test_what_identifies_someone_is_replaced_consistently(self):
        anon = d.Anonymiser(home="/home/rey", user="rey", host="reybox")
        text = anon("Capturing on enp9s0 (192.168.1.20), TCP port 13328.\n"
                    "Capturing on proton0 (10.2.0.2), TCP port 13328.\n"
                    "AION 2's connection uses 10.2.0.2 to 203.0.113.7.\n"
                    "Prefix /home/rey/.local/share/Steam/userdata/123456789/config on reybox\n"
                    "Link fe80::1c2b:3cff:fe4d:5e6f, bridge 127.0.0.1, time 18:32:13.123\n"
                    "/mnt/rey/games")
        for secret in ("192.168.1.20", "10.2.0.2", "203.0.113.7", "/home/rey", "123456789", "reybox",
                       "fe80::1c2b", "/mnt/rey/"):
            self.assertNotIn(secret, text)
        self.assertIn("(<private-1>)", text)
        self.assertEqual(text.count("<private-2>"), 2)          # the same address, the same name
        self.assertIn("<public-1>", text)
        self.assertIn("~/.local/share/Steam/userdata/<steam-id-1>/config on <host>", text)
        self.assertIn("127.0.0.1", text)                        # loopback says nothing about anyone
        self.assertIn("18:32:13.123", text)                     # times are not addresses
        self.assertIn("/mnt/<user>/games", text)


class IssueUrlTest(unittest.TestCase):
    def test_the_url_fits_and_keeps_the_end_of_the_log(self):
        results = [(d.OK, "A2Qlinux 1.0"), (d.PROBLEM, "Launch option: not set")]
        log = [f"2026-11-10 18:{n // 60:02d}:{n % 60:02d}.000 line {n} " + "x" * 40 for n in range(400)]
        report = "## Diagnosis\n\n## launcher.log (last 400 lines)\n\n" + "\n".join(log) + "\n\n## steam_launch.log\n"
        url = d.issue_url(results, report, Path("/tmp/r.txt"), lambda t: t)
        self.assertLessEqual(len(url), d.ISSUE_URL_LIMIT)
        body = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)["body"][0]
        self.assertIn("Launch option: not set", body)
        self.assertIn("line 399 ", body)                         # the newest lines are the ones kept
        self.assertNotIn("line 0 ", body)
        self.assertIn("/tmp/r.txt", body)

    def test_a_diagnosis_too_long_for_the_url_is_cut_not_looped_over(self):
        results = [(d.PROBLEM, f"problem {n} " + "y" * 200) for n in range(60)]
        url = d.issue_url(results, "## launcher.log\n\nlast line\n", Path("/tmp/r.txt"), lambda t: t)
        self.assertLessEqual(len(url), d.ISSUE_URL_LIMIT)
        body = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)["body"][0]
        self.assertIn("problem 0 ", body)
        self.assertIn("cut here", body)


class SystemLinesTest(unittest.TestCase):
    def test_nobara_on_gnome(self):
        import subprocess
        calls = []

        def run(command, **kwargs):
            calls.append(command)
            return subprocess.CompletedProcess(command, 0, stdout="GNOME Shell 49.1\n", stderr="")
        from unittest import mock
        with mock.patch.object(d.shutil, "which", return_value="/usr/bin/gnome-shell"):
            lines = d.system_lines(env={"XDG_CURRENT_DESKTOP": "GNOME", "XDG_SESSION_TYPE": "wayland"},
                                   os_info={"PRETTY_NAME": "Nobara Linux 44 (KDE Plasma Desktop Edition)"},
                                   kernel="6.17.1-201.nobara.fc44.x86_64", run=run)
        self.assertEqual(calls, [["gnome-shell", "--version"]])
        self.assertEqual(lines, [(d.OK, "System: Nobara Linux 44 (KDE Plasma Desktop Edition), "
                                        "kernel 6.17.1-201.nobara.fc44.x86_64"),
                                 (d.OK, "Desktop: GNOME (GNOME Shell 49.1), wayland")])

    def test_nothing_known(self):
        def run(command, **kwargs):
            raise AssertionError("no desktop to ask")
        lines = d.system_lines(env={}, os_info={}, kernel="6.1", run=run)
        self.assertIn("unknown distribution", lines[0][1])
        self.assertEqual(lines[1][1], "Desktop: unknown (no XDG_CURRENT_DESKTOP), unknown session type")

    def test_name_and_version_without_pretty_name(self):
        lines = d.system_lines(env={"XDG_CURRENT_DESKTOP": "XFCE"}, os_info={"NAME": "Fedora", "VERSION_ID": "43"},
                               kernel="6.1", run=None)
        self.assertEqual(lines[0][1], "System: Fedora 43, kernel 6.1")


class ProtonLineTest(unittest.TestCase):
    def line(self, text):
        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as folder:
            (Path(folder) / "pfx").mkdir()
            if text is not None:
                (Path(folder) / "config_info").write_text(text)
            return d.proton_line(Path(folder) / "pfx")

    def test_proton_ge(self):
        self.assertEqual(self.line("GE-Proton10-25\n/home/u/.steam/root/compatibilitytools.d/GE-Proton10-25/files/share/fonts/\n"),
                         (d.OK, "Proton (last run): GE-Proton10-25 (GE-Proton10-25)"))

    def test_valve_proton(self):
        self.assertEqual(self.line("10.0-102\n/home/u/.steam/steam/steamapps/common/Proton 10.0/files/share/fonts/\n"),
                         (d.OK, "Proton (last run): 10.0-102 (Proton 10.0)"))

    def test_not_started_yet(self):
        self.assertEqual(self.line(None)[0], d.NOTE)
        self.assertEqual(self.line("")[0], d.NOTE)
