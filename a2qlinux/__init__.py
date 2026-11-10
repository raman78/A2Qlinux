"""A2Qlinux: Questlog Desktop for AION 2 on Linux under Proton, with live game traffic."""

try:
    from ._version import __version__
except ImportError:           # a source checkout that was never built or installed
    __version__ = "0+unknown"


def shown_version(root=None):
    """The version to show people: the built one, or in a git checkout what git says.

    An editable install (`pipx install --editable .`) writes _version.py once,
    at install time, and never again, so in a checkout that number goes stale
    with the next commit or tag. There `git describe` is asked instead; when
    that fails, the built number is shown together with the reason.
    """
    from pathlib import Path
    import subprocess
    root = Path(__file__).resolve().parent.parent if root is None else Path(root)
    if not (root / ".git").exists():
        return __version__
    try:
        done = subprocess.run(["git", "describe", "--tags", "--dirty"], cwd=root, stdin=subprocess.DEVNULL,
                              capture_output=True, text=True, timeout=5)
    except (OSError, subprocess.TimeoutExpired) as error:
        return f"{__version__} (source checkout; git describe failed: {error})"
    if done.returncode != 0:
        reason = (done.stderr.strip().splitlines() or [f"exit code {done.returncode}"])[0]
        return f"{__version__} (source checkout; git describe failed: {reason})"
    return f"{done.stdout.strip().removeprefix('v')} (source checkout)"
