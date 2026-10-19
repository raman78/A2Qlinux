import unittest

from a2qlinux import steam
from a2qlinux.steam import switch_proton_verb

STEAM_COMMAND = [
    "/home/u/.local/share/Steam/ubuntu12_32/reaper", "SteamLaunch", "AppId=3393110", "--",
    "/home/u/Games/steamapps/common/SteamLinuxRuntime_4/_v2-entry-point", "--verb=waitforexitandrun", "--",
    "/usr/share/steam/compatibilitytools.d/proton-cachyos-slr/proton", "waitforexitandrun",
    "/home/u/Games/steamapps/common/AION2//Aion2/Binaries/Win64/AION2.exe", "-steam",
]


class SwitchProtonVerbTest(unittest.TestCase):
    def test_switches_only_protons_own_verb(self):
        command, switched = switch_proton_verb(STEAM_COMMAND)
        self.assertTrue(switched)
        self.assertEqual(command[8], "run")
        self.assertEqual(command[5], "--verb=waitforexitandrun")     # the runtime's marker stays
        self.assertEqual(STEAM_COMMAND[8], "waitforexitandrun")       # input not modified

    def test_leaves_other_commands_alone(self):
        other = ["/usr/bin/game", "waitforexitandrun"]                 # not after .../proton
        self.assertEqual(switch_proton_verb(other), (other, False))


class WaitForQuestlogTest(unittest.TestCase):
    def setUp(self):
        self.saved = steam.game_processes

    def tearDown(self):
        steam.game_processes = self.saved

    def test_returns_once_questlog_runs(self):
        answers = iter([set(), set(), {4242}])
        steam.game_processes = lambda appid, names: {"questlog.exe": next(answers)}
        self.assertTrue(steam.wait_for_questlog(timeout=5))

    def test_gives_up_after_the_timeout(self):
        steam.game_processes = lambda appid, names: {"questlog.exe": set()}
        self.assertFalse(steam.wait_for_questlog(timeout=0.3))

    def test_no_timeout_still_looks_once(self):
        steam.game_processes = lambda appid, names: {"questlog.exe": {4242}}
        self.assertTrue(steam.wait_for_questlog(timeout=0))


if __name__ == "__main__":
    unittest.main()
