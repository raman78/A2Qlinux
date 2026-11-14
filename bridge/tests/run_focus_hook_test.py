"""Run focus_hook_test.exe against a live BridgeServer in a throwaway prefix (docs/ARCHITECTURE.md §9).

    WINEPREFIX=<throwaway> python3 bridge/tests/run_focus_hook_test.py [wine]

Copies the test program and a2qlinux/bin/version.dll into an empty folder,
starts a BridgeServer, runs the program under xvfb-run with the bridge's
QUESTLOG_PROTON_BRIDGE and WINEDLLOVERRIDES=version=n,b, and switches the
focus state once version.dll has connected: "in" for a second, "out" for
1.5 s, "in" again.
PASS when the program saw own -> desktop -> own; also run with
--no-override to see it FAIL without our version.dll (Wine's own answer).
"""

from pathlib import Path
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from a2qlinux.pcap_bridge import BridgeServer  # noqa: E402


def main(argv):
    override = "--no-override" not in argv
    args = [a for a in argv if not a.startswith("--")]
    wine = args[0] if args else "wine"
    if not os.environ.get("WINEPREFIX"):
        sys.exit("Set WINEPREFIX to a throwaway prefix.")
    server = BridgeServer(print)
    with tempfile.TemporaryDirectory() as folder:
        shutil.copy(ROOT / "bridge" / "tests" / "focus_hook_test.exe", folder)
        shutil.copy(ROOT / "a2qlinux" / "bin" / "version.dll", folder)
        env = dict(os.environ, QUESTLOG_PROTON_BRIDGE=server.environment_value(),
                   WINEDLLOVERRIDES="version=n,b" if override else "", WINEDEBUG="-all")

        def switch():
            deadline = time.monotonic() + 60
            while not server.focus_clients and time.monotonic() < deadline:   # version.dll has connected
                time.sleep(0.1)
            time.sleep(1)
            server.set_focus("out")
            time.sleep(1.5)
            server.set_focus("in")
        threading.Thread(target=switch, daemon=True).start()
        done = subprocess.run(["xvfb-run", "-a", wine, "focus_hook_test.exe", "6"], cwd=folder, env=env,
                              capture_output=True, text=True, timeout=120)
    server.stop()
    print(done.stdout + done.stderr)
    seen = [line.split()[-1] for line in done.stdout.splitlines() if line.endswith(("own", "desktop", "other"))]
    ok = seen == ["own", "desktop", "own"] and "version.dll answers: yes" in done.stdout
    print("PASS" if ok else f"FAIL (saw {seen})")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
