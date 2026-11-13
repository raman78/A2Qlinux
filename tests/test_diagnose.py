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

    def test_the_user_name_in_wines_windows_paths(self):
        anon = d.Anonymiser(home="/home/rey", user="rey", host="reybox")
        text = anon("open 'Z:\\home\\rey\\Games\\Questlog\\resources\\app-update.yml'\n"
                    "path: 'Z:\\\\home\\\\rey\\\\Games'")
        self.assertNotIn("rey", text.replace("<user>", ""))
        self.assertIn("Z:\\home\\<user>\\Games", text)


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
    """config_info as Proton writes it: the prefix version, then paths in the tool's folder."""

    def line(self, config_info, tool=None, version=None):
        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as root:
            compat = Path(root) / "compatdata" / "3393110"
            (compat / "pfx").mkdir(parents=True)
            if config_info is not None:
                (compat / "config_info").write_text(config_info)
            if tool and version is not None:
                (Path(root) / tool).mkdir(parents=True)
                (Path(root) / tool / "version").write_text(version)
            return d.proton_line(compat / "pfx", host_root=root)

    def test_proton_ge_through_a_latest_link_folder(self):
        tool = "steam/compatibilitytools.d/Proton-GE Latest"
        self.assertEqual(self.line(f"11.0-100\n/{tool}/files/share/fonts/\n", tool, "1762156778 GE-Proton11-12\n"),
                         (d.OK, "Proton (last run): GE-Proton11-12 (folder Proton-GE Latest)"))

    def test_a_tool_seen_from_inside_the_runtime_container(self):
        tool = "usr/share/steam/compatibilitytools.d/proton-cachyos-slr"
        self.assertEqual(self.line(f"CachyOS-11.0-100\n/run/host/{tool}/files/lib/\n", tool,
                                   "1792530497 cachyos-11.0-20261015-slr\n"),
                         (d.OK, "Proton (last run): cachyos-11.0-20261015-slr (folder proton-cachyos-slr)"))

    def test_without_a_version_file_the_prefix_version_is_named_as_such(self):
        self.assertEqual(self.line("10.0-102\n/home/u/steamapps/common/Proton 10.0/files/share/fonts/\n"),
                         (d.OK, "Proton (last run): build unknown, prefix version 10.0-102 (folder Proton 10.0)"))

    def test_not_started_yet(self):
        self.assertEqual(self.line(None)[0], d.NOTE)
        self.assertEqual(self.line("")[0], d.NOTE)


class GpuLinesTest(unittest.TestCase):
    """Cards from a stand-in /sys and /proc, names from a stand-in pci.ids."""

    PCI_IDS = ("10de  NVIDIA Corporation\n\t24c9  GA104 [GeForce RTX 3060 Ti GDDR6X]\n\t\t1043 8870  sub\n"
               "1002  Advanced Micro Devices, Inc. [AMD/ATI]\n\t744c  Navi 31 [Radeon RX 7900 XT/7900 XTX]\n")

    def setUp(self):
        import tempfile
        from pathlib import Path
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / "pci.ids").write_text(self.PCI_IDS)

    def tearDown(self):
        self.tmp.cleanup()

    def card(self, name, vendor, device, driver, primary=True):
        import os
        dev = self.root / "sys/class/drm" / name / "device"
        dev.mkdir(parents=True)
        (dev / "vendor").write_text(vendor + "\n")
        (dev / "device").write_text(device + "\n")
        (dev / "boot_vga").write_text("1\n" if primary else "0\n")
        target = self.root / "sys/bus/pci/drivers" / driver
        target.mkdir(parents=True, exist_ok=True)
        os.symlink(target, dev / "driver")

    def lines(self, glx=None):
        import subprocess

        def run(command, **kwargs):
            return subprocess.CompletedProcess(command, 0, stdout=glx or "", stderr="")
        return d.gpu_lines(str(self.root), run=run, ids_files=(str(self.root / "pci.ids"),),
                           which=lambda name: "/usr/bin/glxinfo" if glx is not None else None)

    def test_nvidia_with_its_driver_version(self):
        self.card("card1", "0x10de", "0x24c9", "nvidia")
        (self.root / "sys/class/drm/card1-DP-1").mkdir()          # a connector, not a card
        (self.root / "proc/driver/nvidia").mkdir(parents=True)
        (self.root / "proc/driver/nvidia/version").write_text(
            "NVRM version: NVIDIA UNIX Open Kernel Module for x86_64  620.70.06  Release Build  (notroot@)\n")
        self.assertEqual(self.lines(), [(d.OK, "Graphics: NVIDIA Corporation GA104 [GeForce RTX 3060 Ti GDDR6X], "
                                               "driver nvidia 620.70.06 (primary)")])

    def test_amd_and_software_opengl_is_a_note(self):
        self.card("card0", "0x1002", "0x744c", "amdgpu")
        glx = ("OpenGL renderer string: llvmpipe (LLVM 20.1.0, 256 bits)\n"
               "OpenGL version string: 4.5 (Compatibility Profile) Mesa 25.2.4\n")
        lines = self.lines(glx)
        self.assertEqual(lines[0][1], "Graphics: Advanced Micro Devices, Inc. [AMD/ATI] Navi 31 "
                                      "[Radeon RX 7900 XT/7900 XTX], driver amdgpu (primary)")
        self.assertEqual(lines[1][0], d.NOTE)
        self.assertIn("software rendering", lines[1][1])
        self.assertIn("Mesa 25.2.4", lines[1][1])

    def test_unknown_ids_and_no_cards(self):
        self.assertEqual(self.lines()[0][0], d.NOTE)
        self.card("card0", "0x1234", "0xabcd", "somedrv", primary=False)
        self.assertEqual(self.lines()[0][1], "Graphics: vendor 1234 device abcd, driver somedrv")


class QuestlogLogExcerptTest(unittest.TestCase):
    def test_short_whole_long_start_and_end(self):
        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "questlog.log"
            self.assertEqual(d.questlog_log_excerpt(path), [])
            path.write_text("".join(f"line {i}\n" for i in range(10)))
            self.assertEqual(len(d.questlog_log_excerpt(path, head=3, tail=7)), 10)
            lines = d.questlog_log_excerpt(path, head=2, tail=3)
            self.assertEqual(lines, ["line 0", "line 1", "(... 5 lines left out ...)", "line 7", "line 8", "line 9"])


class DisplayAndEnvironmentTest(unittest.TestCase):
    def setUp(self):
        import tempfile
        from pathlib import Path
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def runner(self, outputs):
        import subprocess

        def run(command, **kwargs):
            return subprocess.CompletedProcess(command, 0, stdout=outputs[command[0]], stderr="")
        return run

    def test_monitors_as_xwayland_lists_them_and_kde_scale(self):
        outputs = {"xrandr": "Monitors: 2\n 0: +*DP-1 2560/597x1440/336+0+0  DP-1\n"
                             " 1: +HDMI-A-1 1920/527x1080/296+2560+0  HDMI-A-1\n",
                   "kscreen-doctor": '{"outputs": [{"name": "DP-1", "enabled": true, "scale": 1.25},'
                                     ' {"name": "HDMI-A-1", "enabled": false, "scale": 1}]}'}
        lines = d.display_lines(env={"DISPLAY": ":0", "XDG_CURRENT_DESKTOP": "KDE"}, run=self.runner(outputs),
                                which=lambda name: f"/usr/bin/{name}")
        self.assertEqual(lines, [(d.OK, "Monitors (as Wine sees them): DP-1 2560x1440 at +0+0, "
                                        "HDMI-A-1 1920x1080 at +2560+0"),
                                 (d.OK, "Desktop scale: DP-1 1.25")])

    def test_gnome_scale_from_monitors_xml(self):
        (self.root / ".config").mkdir()
        lines = d.display_lines(env={"XDG_CURRENT_DESKTOP": "GNOME"}, run=None, which=lambda name: None,
                                home=self.root)
        self.assertEqual(lines, [(d.OK, "Desktop scale: 1 (no monitors.xml: never changed)")])
        (self.root / ".config/monitors.xml").write_text("<monitors><configuration><logicalmonitor>"
                                                         "<scale>1.5</scale></logicalmonitor></configuration>")
        lines = d.display_lines(env={"XDG_CURRENT_DESKTOP": "ubuntu:GNOME"}, run=None, which=lambda name: None,
                                home=self.root)
        self.assertEqual(lines, [(d.OK, "Desktop scale: 1.5")])

    def test_wine_dpi_with_its_keys(self):
        (self.root / "user.reg").write_text('WINE REGISTRY Version 2\n\n[Control Panel\\\\Desktop] 1\n'
                                            '"LogPixels"=dword:00000090\n\n[Software\\\\Wine\\\\Fonts] 1\n'
                                            '"LogPixels"=dword:00000060\n')
        self.assertEqual(d.wine_dpi_line(self.root),
                         (d.OK, "Wine DPI: 144 in Control Panel\\Desktop; 96 in Software\\Wine\\Fonts"))
        (self.root / "user.reg").write_text("WINE REGISTRY Version 2\n")
        self.assertEqual(d.wine_dpi_line(self.root)[1], "Wine DPI: not set (Wine's default, 96)")

    def test_steam_environment_prefers_steam_sh(self):
        for pid, argv, environ in (("10", [b"/home/u/.local/share/Steam/steamrt64/steam", b"-x"], b"FROM=client\0"),
                                   ("11", [b"bash", b"/home/u/.local/share/Steam/steam.sh"],
                                    b"FROM=script\0PROTON_ENABLE_WAYLAND=1\0"),
                                   ("12", [b"/usr/bin/python"], b"FROM=other\0")):
            (self.root / pid).mkdir()
            (self.root / pid / "cmdline").write_bytes(b"\0".join(argv) + b"\0")
            (self.root / pid / "environ").write_bytes(environ)
        steam = d.steam_environment(str(self.root))
        self.assertEqual(steam["FROM"], "script")
        lines = d.environment_lines(env={"DXVK_HUD": "fps", "HOME": "/home/u", "WINEDLLOVERRIDES": "x=n"},
                                    steam_environ=steam)
        self.assertEqual(lines, [(d.OK, "Steam's environment: PROTON_ENABLE_WAYLAND=1"),
                                 (d.OK, "This session's environment (Questlog's): DXVK_HUD=fps, WINEDLLOVERRIDES=x=n")])
        self.assertIn("Steam is not running", d.environment_lines(env={}, steam_environ=None)[0][1])
