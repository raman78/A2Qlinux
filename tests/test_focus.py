import unittest

from a2qlinux import focus as f


class WineClassTest(unittest.TestCase):
    def test_wine_windows(self):
        for wm_class in (("steam_app_3393110", "steam_app_3393110"), ("steam_proton", "steam_proton"),
                         ("questlog.exe", "Wine"), ("", "Steam_App_1")):
            self.assertTrue(f.is_wine_class(wm_class), wm_class)

    def test_other_windows(self):
        # A browser, a terminal, KWin's stand-in window for a Wayland one (no class), Steam's own client.
        for wm_class in (("Navigator", "firefox"), ("konsole", "konsole"), ("", ""), ("steamwebhelper", "steam")):
            self.assertFalse(f.is_wine_class(wm_class), wm_class)


class ActiveWindowWatchTest(unittest.TestCase):
    def test_without_a_display_it_says_why(self):
        reason = f.ActiveWindowWatch(lambda state: None, display="").start()
        self.assertIn("DISPLAY", reason)

    def test_reports_changes_only(self):
        seen = []
        watch = f.ActiveWindowWatch(seen.append, display=":0")
        classes = iter([("steam_app_3393110",) * 2, ("steam_proton",) * 2, ("", ""), ("konsole",) * 2,
                        ("steam_app_3393110",) * 2])
        watch._active_window = lambda: 1
        watch._wm_class = lambda window: next(classes)
        for _ in range(5):
            watch._update()
        self.assertEqual(seen, [f.IN, f.OUT, f.IN])


if __name__ == "__main__":
    unittest.main()


class FocusFollowerTest(unittest.TestCase):
    def test_passes_lines_and_falls_back_to_in_with_the_reason_once(self):
        import sys
        import threading
        seen, logged = [], []
        child = "import sys; print('out', flush=True); print('in', flush=True); print('out', flush=True); " \
                "print('the X display went away', file=sys.stderr); sys.exit(1)"
        follower = f.FocusFollower(seen.append, logged.append, command=[sys.executable, "-c", child])
        follower.RESTART_WAIT = 0.2
        follower.start()
        deadline = threading.Event()
        for _ in range(100):
            if seen.count(f.IN) >= 3:
                break
            deadline.wait(0.05)
        follower.stop()
        self.assertEqual(seen[:4], [f.OUT, f.IN, f.OUT, f.IN])        # the last: the child ended
        self.assertEqual(len(logged), 1)                              # the same reason is not repeated
        self.assertIn("the X display went away", logged[0])
