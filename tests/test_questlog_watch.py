import base64
import hashlib
import json
from pathlib import Path
import unittest
from unittest import mock

from a2qlinux import questlog_versions
from tests.test_update import OfflineCdn
from tools import questlog_watch as w


class FakeGh:
    """Stands in for `gh`: records the calls, answers issue list/create."""

    def __init__(self, issues=()):
        self.calls, self.issues = [], list(issues)

    def __call__(self, *args):
        self.calls.append(args)
        if args[:2] == ("issue", "list"):
            return json.dumps(self.issues)
        if args[:2] == ("issue", "create"):
            return "https://github.com/raman78/A2Qlinux/issues/41\n"
        return ""

    def verbs(self):
        return [call[:2] for call in self.calls]


class WatchTest(OfflineCdn, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.register = Path(self.tmp.name) / "register.json"
        self.said = []
        patcher = mock.patch.object(w, "shown_version", return_value="0.7.4")
        patcher.start()
        self.addCleanup(patcher.stop)

    def watch(self, gh, **kwargs):
        return w.watch(self.register, run=gh, say=self.said.append, feed_url=(self.cdn / "latest.yml").as_uri(),
                       downloads=self.cdn.as_uri() + "/", **kwargs)

    def entry(self, version="0.1.35"):
        return questlog_versions.load(self.register)["versions"][version]

    def test_a_fitting_version_is_recorded_with_the_feeds_checksum_and_no_issue(self):
        gh = FakeGh()
        self.assertTrue(self.watch(gh))
        entry = self.entry()
        self.assertTrue(entry["fits"])
        self.assertEqual((entry["sha512_from"], entry["checked_by"], entry["issue"]), ("latest.yml", "0.7.4", None))
        self.assertIn("sha512: " + entry["sha512"], (self.cdn / "latest.yml").read_text())
        self.assertEqual(gh.calls, [])

    def test_a_refusal_opens_one_issue_and_a_second_pass_does_nothing(self):
        self.publish_unfitting()
        gh = FakeGh()
        self.assertTrue(self.watch(gh))
        self.assertEqual(gh.verbs(), [("issue", "list"), ("issue", "create")])
        self.assertIn("Electron 45.0.0", gh.calls[1][-1])
        self.assertEqual((self.entry()["fits"], self.entry()["issue"]), (False, 41))
        gh = FakeGh()
        self.assertFalse(self.watch(gh))
        self.assertEqual(gh.calls, [])

    def test_an_issue_already_on_github_gets_a_comment_instead_of_a_twin(self):
        self.publish_unfitting()
        gh = FakeGh(issues=[{"number": 7, "title": w.issue_title("0.1.35")}])
        self.watch(gh)
        self.assertEqual(gh.verbs(), [("issue", "list"), ("issue", "comment")])
        self.assertEqual(self.entry()["issue"], 7)

    def test_newer_checks_judge_a_refusal_again_and_close_its_issue_when_it_fits(self):
        register = questlog_versions.empty()
        feed = {"version": "0.1.35", "path": "questlog-setup-0.1.35.exe", "size": 1, "sha512": "x"}
        questlog_versions.record(register, feed, ["old check"], "0.7.3", "2026-11-17T00:00:00Z")["issue"] = 41
        questlog_versions.save(self.register, register)
        gh = FakeGh()
        self.assertTrue(self.watch(gh))
        self.assertEqual(gh.verbs(), [("issue", "close")])
        self.assertTrue(self.entry()["fits"])
        self.assertEqual(self.entry()["issue"], 41)

    def test_an_older_version_is_judged_from_the_cdns_file_with_a_computed_checksum(self):
        gh = FakeGh()
        (self.cdn / "latest.yml").unlink()       # the feed no longer describes it
        self.assertTrue(self.watch(gh, version="0.1.35"))
        entry = self.entry()
        self.assertEqual((entry["fits"], entry["sha512_from"]), (True, "computed"))
        installer = (self.cdn / "questlog-setup-0.1.35.exe").read_bytes()
        self.assertEqual(entry["size"], len(installer))
        self.assertEqual(entry["sha512"], base64.b64encode(hashlib.sha512(installer).digest()).decode())


if __name__ == "__main__":
    unittest.main()
