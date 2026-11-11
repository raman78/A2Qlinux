import os
import tempfile
import unittest
from pathlib import Path

from a2qlinux import setup_desktop as s


class RefreshEntriesTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.ours = root / "bin" / "a2qlinux"
        self.saved = (s.MENU_ENTRY, s.ICON, s.OLD_ICON, s.desktop_shortcut_path, s.command)
        s.MENU_ENTRY = root / "applications" / "questlog-aion2.desktop"
        s.ICON = root / "icons" / "a2qlinux.png"
        s.OLD_ICON = root / "icons" / "questlog-aion2.png"
        self.shortcut = root / "Desktop" / "questlog-aion2.desktop"
        s.desktop_shortcut_path = lambda: self.shortcut
        s.command = lambda name: str(self.ours)
        self.saved_questlog_dir = s.config.questlog_dir
        s.config.questlog_dir = lambda: root / "Questlog"     # empty: not the Questlog of whoever runs the tests

    def tearDown(self):
        s.MENU_ENTRY, s.ICON, s.OLD_ICON, s.desktop_shortcut_path, s.command = self.saved
        s.config.questlog_dir = self.saved_questlog_dir
        self.tmp.cleanup()

    def test_missing_menu_entry_is_created_but_no_desktop_shortcut(self):
        s.refresh_entries()
        self.assertEqual(s.entry_command(s.MENU_ENTRY), str(self.ours))
        self.assertFalse(self.shortcut.exists())

    def test_entries_from_the_old_layout_are_rewritten(self):
        old = "[Desktop Entry]\nExec=python3 /home/u/Shared/AION2/questlog-proton/questlog_desktop.py\n"
        for path in (s.MENU_ENTRY, self.shortcut):
            path.parent.mkdir(parents=True)
            path.write_text(old)
        written = s.refresh_entries()
        self.assertEqual(set(written), {s.MENU_ENTRY, self.shortcut})
        self.assertEqual(s.entry_command(self.shortcut), str(self.ours))

    def test_our_current_entry_with_options_added_by_hand_is_left_alone(self):
        s.MENU_ENTRY.parent.mkdir(parents=True)
        exec_line = f"Exec=env QUESTLOG_DIR=/x {self.ours} --no-auto-update"
        mine = s.desktop_entry(None).replace(f"Exec={self.ours}", exec_line)
        s.MENU_ENTRY.write_text(mine)
        self.assertEqual(s.refresh_entries(), [])
        self.assertEqual(s.MENU_ENTRY.read_text(), mine)

    def test_entry_from_before_the_rename_gets_name_and_icon_but_keeps_its_command(self):
        exec_line = f"Exec=env QUESTLOG_DIR=/x {self.ours} --no-auto-update"
        old = ("[Desktop Entry]\nType=Application\nName=Questlog (AION 2)\n"
               f"{exec_line}\nIcon={s.OLD_ICON}\nTerminal=false\nCategories=Game;\n")
        for path in (s.MENU_ENTRY, self.shortcut):
            path.parent.mkdir(parents=True)
            path.write_text(old)
        self.assertEqual(set(s.refresh_entries()), {s.MENU_ENTRY, self.shortcut})
        for path in (s.MENU_ENTRY, self.shortcut):
            lines = path.read_text().splitlines()
            self.assertIn("Name=A2Qlinux", lines)
            self.assertIn(f"Icon={s.ICON}", lines)
            self.assertIn(exec_line, lines)
            self.assertIn("Keywords=Questlog;AION;AION 2;damage meter;", lines)
            self.assertEqual(len([l for l in lines if l.startswith("Name=")]), 1)
        self.assertEqual(s.refresh_entries(), [])

    def test_only_the_desktop_entry_group_is_updated(self):
        exec_line = f"Exec={self.ours}"
        old = (f"[Desktop Entry]\nName=Questlog (AION 2)\n{exec_line}\n\n"
               "[Desktop Action Hidden]\nName=Start hidden\nIcon=other.png\nExec=a2qlinux --hidden\n")
        updated = s.with_current_keys(old, s.desktop_entry(None))
        entry, action = updated.split("\n\n[Desktop Action Hidden]\n")
        self.assertIn("Name=A2Qlinux", entry.splitlines())
        self.assertIn("Keywords=Questlog;AION;AION 2;damage meter;", entry.splitlines())
        self.assertIn(f"Icon={s.ICON}", entry.splitlines())
        self.assertEqual(action, "Name=Start hidden\nIcon=other.png\nExec=a2qlinux --hidden\n")

    def test_missing_icon_is_made_and_the_uncoloured_one_removed(self):
        made = []
        saved = s.read_asar_file, s.a2qlinux_icon
        s.read_asar_file = lambda asar, name: b"questlog png"
        s.a2qlinux_icon = lambda png: made.append(png) or b"red png"
        try:
            s.OLD_ICON.parent.mkdir(parents=True)
            s.OLD_ICON.write_bytes(b"questlog png")
            s.refresh_entries()
        finally:
            s.read_asar_file, s.a2qlinux_icon = saved
        self.assertEqual(made, [b"questlog png"])
        self.assertEqual(s.ICON.read_bytes(), b"red png")
        self.assertFalse(s.OLD_ICON.exists())

    def test_icon_that_cannot_be_made_is_reported_and_the_old_one_kept(self):
        s.OLD_ICON.parent.mkdir(parents=True)
        s.OLD_ICON.write_bytes(b"questlog png")
        said = []
        s.refresh_entries(said.append)            # no Questlog in the test folder
        self.assertFalse(s.ICON.exists())
        self.assertTrue(s.OLD_ICON.exists())
        self.assertTrue(any("icon could not be made" in line for line in said), said)


class A2QlinuxIconTest(unittest.TestCase):
    """Questlog's white Q turns red; the dark tile, transparency and soft edges stay."""

    def test_white_becomes_the_colour_and_the_tile_stays(self):
        from PyQt6.QtCore import QBuffer, QByteArray, QIODevice
        from PyQt6.QtGui import QColor, QImage
        image = QImage(4, 1, QImage.Format.Format_RGBA8888)
        for x, colour in enumerate([QColor(17, 17, 17), QColor(255, 255, 255),
                                    QColor(136, 136, 136), QColor(0, 0, 0, 0)]):
            image.setPixelColor(x, 0, colour)
        data = QByteArray()
        buffer = QBuffer(data)
        buffer.open(QIODevice.OpenModeFlag.WriteOnly)
        image.save(buffer, "PNG")
        out = QImage.fromData(s.a2qlinux_icon(bytes(data), colour=(220, 40, 40)))
        pixel = lambda x: out.pixelColor(x, 0).getRgb()
        self.assertEqual(pixel(0), (17, 17, 17, 255))          # the tile
        self.assertEqual(pixel(1), (220, 40, 40, 255))         # the Q
        r, g, b, a = pixel(2)                                  # an edge: half tile, half Q
        self.assertEqual((r, g, b, a), (118, 28, 28, 255))
        self.assertEqual(pixel(3)[3], 0)                       # transparent corner

    def test_not_an_image(self):
        with self.assertRaises(ValueError):
            s.a2qlinux_icon(b"not a png")


# /etc/os-release of each distribution family, as the distributions ship them (abridged).
OS_RELEASE = {
    "cachyos": 'NAME="CachyOS Linux"\nID=cachyos\nID_LIKE=arch\n',
    "ubuntu": 'NAME="Ubuntu"\nVERSION_ID="24.04"\nID=ubuntu\nID_LIKE=debian\n',
    "mint": 'NAME="Linux Mint"\nID=linuxmint\nID_LIKE="ubuntu debian"\n',
    "debian12": 'NAME="Debian GNU/Linux"\nVERSION_ID="12"\nID=debian\n',
    "debian13": 'NAME="Debian GNU/Linux"\nVERSION_ID="13"\nID=debian\n',
    "fedora": 'NAME="Fedora Linux"\nVERSION_ID=44\nID=fedora\n',
    "tumbleweed": 'NAME="openSUSE Tumbleweed"\nID="opensuse-tumbleweed"\nID_LIKE="opensuse suse"\n',
    "unknown": 'NAME="Something"\nID=something\n',
}


class InstallCommandsTest(unittest.TestCase):
    """Missing packages become one command for the distribution in use."""

    def info(self, name):
        with tempfile.NamedTemporaryFile("w", suffix="os-release") as f:
            f.write(OS_RELEASE[name])
            f.flush()
            return s.os_release(f.name)

    def test_families(self):
        expected = {"cachyos": "arch", "ubuntu": "ubuntu", "mint": "ubuntu", "debian12": "debian",
                    "debian13": "debian", "fedora": "fedora", "tumbleweed": "suse", "unknown": None}
        for name, family in expected.items():
            with self.subTest(name):
                self.assertEqual(s.distro_family(self.info(name)), family)

    def test_quotes_are_removed(self):
        self.assertEqual(self.info("tumbleweed")["ID"], "opensuse-tumbleweed")

    def test_one_command_with_each_distributions_names(self):
        wanted = ["wireshark", "7zip", "notify"]
        self.assertEqual(s.install_commands(wanted, self.info("cachyos")),
                         ["sudo pacman -S --needed wireshark-cli 7zip libnotify"])
        self.assertEqual(s.install_commands(wanted, self.info("debian12")),
                         ["sudo apt install wireshark-common p7zip-full libnotify-bin"])
        self.assertEqual(s.install_commands(wanted, self.info("fedora")),
                         ["sudo dnf install wireshark-cli 7zip libnotify"])
        self.assertEqual(s.install_commands(wanted, self.info("tumbleweed")),
                         ["sudo zypper install wireshark 7zip libnotify-tools"])

    def test_protontricks_where_each_debian_family_member_has_it(self):
        self.assertEqual(s.install_commands(["protontricks"], self.info("ubuntu")),
                         ["sudo add-apt-repository multiverse && sudo apt install protontricks"])
        self.assertEqual(s.install_commands(["protontricks"], self.info("debian12")),
                         ["sudo apt install protontricks"])
        self.assertEqual(s.install_commands(["protontricks", "xdotool"], self.info("debian13")),
                         ["sudo apt install xdotool", "pipx install protontricks"])
        self.assertEqual(s.install_commands(["protontricks"], self.info("debian13")),
                         ["pipx install protontricks"])

    def test_multiverse_only_when_protontricks_is_needed(self):
        self.assertEqual(s.install_commands(["xdotool"], self.info("ubuntu")), ["sudo apt install xdotool"])

    def test_unknown_distribution_gets_arch_names_and_the_guide(self):
        [line] = s.install_commands(["wireshark", "xdotool"], self.info("unknown"))
        self.assertIn("docs/INSTALL.md", line)
        self.assertIn("wireshark-cli xdotool", line)

    def test_nothing_missing_nothing_to_run(self):
        self.assertEqual(s.install_commands([], self.info("fedora")), [])


class CaptureCheckTest(unittest.TestCase):
    """Capturing is tried for real; a refusal comes back with the commands that allow it."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.bin = Path(self.tmp.name)
        self.saved_path = os.environ["PATH"]
        os.environ["PATH"] = f"{self.bin}{os.pathsep}{self.saved_path}"

    def tearDown(self):
        os.environ["PATH"] = self.saved_path
        self.tmp.cleanup()

    def fake_dumpcap(self, code, stderr=""):
        script = self.bin / "dumpcap"
        script.write_text(f"#!/bin/sh\nprintf '%s\\n' '{stderr}' >&2\nexit {code}\n")
        script.chmod(0o755)

    def test_working_capture_is_no_problem(self):
        self.fake_dumpcap(0)
        self.assertIsNone(s.capture_problem({"ID": "debian"}))

    def test_refusal_on_debian_names_dpkg_reconfigure_and_dumpcaps_reason(self):
        self.fake_dumpcap(1, 'dumpcap: You do not have permission to capture on device "lo".')
        problem = s.capture_problem({"ID": "debian"})
        self.assertIn('You do not have permission to capture on device "lo"', problem)
        self.assertIn("sudo dpkg-reconfigure wireshark-common", problem)

    def test_refusal_elsewhere_does_not_suggest_dpkg(self):
        self.fake_dumpcap(1, "dumpcap: denied")
        problem = s.capture_problem({"ID": "fedora"})
        self.assertNotIn("dpkg-reconfigure", problem)
        self.assertIn("no capture capabilities", problem)

    def test_dumpcap_only_the_group_may_run_is_a_group_problem_not_a_missing_package(self):
        self.fake_dumpcap(0)
        (self.bin / "dumpcap").chmod(0o644)          # as root:wireshark 0750 looks to a non-member
        os.environ["PATH"] = str(self.bin)
        self.assertEqual(s.installed("dumpcap"), str(self.bin / "dumpcap"))
        missing, wanted = s.missing_packages()
        self.assertNotIn("wireshark", wanted)
        os.environ["PATH"] = f"{self.bin}{os.pathsep}{self.saved_path}"   # `id` is needed from here on
        problem = s.capture_problem({"ID": "fedora"})
        self.assertIn("only members of the 'wireshark' group", problem)
        self.assertNotIn("no capture capabilities", problem)

    def test_no_dumpcap_is_left_to_the_missing_packages(self):
        os.environ["PATH"] = str(self.bin)
        self.assertIsNone(s.capture_problem({"ID": "fedora"}))


if __name__ == "__main__":
    unittest.main()


class LaunchOptionStepTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.ours = Path(self.tmp.name) / "a2qlinux-steam"
        self.ours.write_text("#!/bin/sh\n")
        self.said = []

    def tearDown(self):
        self.tmp.cleanup()

    def step(self, *options):
        accounts = [(Path(f"/s/userdata/{n}"), option) for n, option in enumerate(options, 1)]
        return s.launch_option_step(str(self.ours), accounts, say=self.said.append)

    def test_set_says_so_without_the_line_to_paste(self):
        self.assertEqual(self.step(f"{self.ours} %command%"), [])
        self.assertEqual(len(self.said), 1)
        self.assertIn("set (", self.said[0])

    def test_not_set_gives_the_line_to_paste_and_is_no_problem(self):
        self.assertEqual(self.step(None), [])
        self.assertTrue(any(line.strip() == f"{self.ours} %command%" for line in self.said))

    def test_set_so_that_the_game_cannot_start_is_a_problem(self):
        problems = self.step(f"{self.ours}")            # no %command%
        self.assertEqual(len(problems), 1)
        self.assertIn("%command%", problems[0])
