import os
import tempfile
import unittest
from pathlib import Path

from a2qlinux import config


class LoadTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "config.toml"
        self.saved_env = os.environ.pop("QUESTLOG_DIR", None)

    def tearDown(self):
        if self.saved_env is not None:
            os.environ["QUESTLOG_DIR"] = self.saved_env
        else:
            os.environ.pop("QUESTLOG_DIR", None)
        self.tmp.cleanup()

    def load(self, text):
        self.path.write_text(text)
        return config.load(self.path)

    def test_missing_file_gives_defaults_and_no_problems(self):
        settings, problems = config.load(self.path)
        self.assertEqual(problems, [])
        self.assertEqual(settings.after_game, "keep")
        self.assertEqual(settings.after_game_delay, 15.0)
        self.assertTrue(settings.auto_update)
        self.assertEqual(settings.questlog_dir, Path.home() / "Games" / "Questlog")

    def test_values_are_read(self):
        settings, problems = self.load('after_game = "close"\nafter_game_delay = 20\nauto_update = false\n'
                                       'questlog_dir = "/opt/ql"\ninterface = "eth0"\n')
        self.assertEqual(problems, [])
        self.assertEqual((settings.after_game, settings.after_game_delay, settings.auto_update),
                         ("close", 20.0, False))
        self.assertEqual(settings.questlog_dir, Path("/opt/ql"))
        self.assertEqual(settings.interface, "eth0")

    def test_unknown_setting_is_reported_with_its_line(self):
        settings, problems = self.load('auto_update = true\nafter_gaem = "close"\n')
        self.assertEqual(len(problems), 1)
        self.assertIn("line 2", problems[0])
        self.assertIn("after_gaem", problems[0])
        self.assertEqual(settings.after_game, "keep")

    def test_wrong_type_wrong_choice_and_too_small_use_the_default(self):
        settings, problems = self.load('auto_update = "yes"\nafter_game = "never"\nafter_game_delay = 5\n')
        self.assertEqual(len(problems), 3)
        self.assertTrue(settings.auto_update)
        self.assertEqual(settings.after_game, "keep")
        self.assertEqual(settings.after_game_delay, 15.0)
        self.assertIn("at least 10.5", problems[2])

    def test_a_bool_is_not_taken_for_a_number(self):
        settings, problems = self.load("update_check_hours = true\n")
        self.assertEqual(len(problems), 1)
        self.assertEqual(settings.update_check_hours, 6.0)

    def test_broken_file_is_reported_and_defaults_used(self):
        settings, problems = self.load('after_game = "close\n')
        self.assertEqual(len(problems), 1)
        self.assertIn("not valid TOML", problems[0])
        self.assertEqual(settings.after_game, "keep")

    def test_environment_overrides_the_file(self):
        os.environ["QUESTLOG_DIR"] = "/env/ql"
        settings, _ = self.load('questlog_dir = "/file/ql"\n')
        self.assertEqual(settings.questlog_dir, Path("/env/ql"))

    def test_template_loads_cleanly_and_carries_the_folder(self):
        settings, problems = self.load(config.template(Path("/games/Questlog")))
        self.assertEqual(problems, [])
        self.assertEqual(settings.questlog_dir, Path("/games/Questlog"))
        self.assertEqual(settings.after_game, "keep")


if __name__ == "__main__":
    unittest.main()
