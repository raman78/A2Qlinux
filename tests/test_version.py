import subprocess
import tempfile
import unittest
from pathlib import Path

import a2qlinux


def git(root, *args):
    subprocess.run(["git", *args], cwd=root, check=True, capture_output=True,
                   env={"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t",
                        "GIT_COMMITTER_EMAIL": "t@t", "HOME": str(root), "PATH": "/usr/bin:/bin"})


class ShownVersionTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_an_installed_package_shows_its_built_version(self):
        self.assertEqual(a2qlinux.shown_version(self.root), a2qlinux.__version__)

    def test_a_checkout_shows_what_git_says_not_the_number_frozen_at_install(self):
        git(self.root, "init", "-q")
        (self.root / "f").write_text("1")
        git(self.root, "add", "f")
        git(self.root, "commit", "-q", "-m", "one")
        git(self.root, "tag", "v9.8.7")
        self.assertEqual(a2qlinux.shown_version(self.root), "9.8.7 (source checkout)")
        (self.root / "f").write_text("2")
        self.assertEqual(a2qlinux.shown_version(self.root), "9.8.7-dirty (source checkout)")

    def test_a_checkout_git_cannot_describe_says_why(self):
        git(self.root, "init", "-q")          # no commit, no tag
        shown = a2qlinux.shown_version(self.root)
        self.assertTrue(shown.startswith(f"{a2qlinux.__version__} (source checkout; git describe failed: "), shown)
