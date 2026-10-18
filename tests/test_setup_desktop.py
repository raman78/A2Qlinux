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


if __name__ == "__main__":
    unittest.main()
