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
        self.saved = (s.MENU_ENTRY, s.ICON, s.desktop_shortcut_path, s.command)
        s.MENU_ENTRY = root / "applications" / "questlog-aion2.desktop"
        s.ICON = root / "icons" / "questlog-aion2.png"
        self.shortcut = root / "Desktop" / "questlog-aion2.desktop"
        s.desktop_shortcut_path = lambda: self.shortcut
        s.command = lambda name: str(self.ours)

    def tearDown(self):
        s.MENU_ENTRY, s.ICON, s.desktop_shortcut_path, s.command = self.saved
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

    def test_our_entry_with_options_added_by_hand_is_left_alone(self):
        s.MENU_ENTRY.parent.mkdir(parents=True)
        mine = f"[Desktop Entry]\nExec=env QUESTLOG_DIR=/x {self.ours} --no-auto-update\n"
        s.MENU_ENTRY.write_text(mine)
        self.assertEqual(s.refresh_entries(), [])
        self.assertEqual(s.MENU_ENTRY.read_text(), mine)


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
