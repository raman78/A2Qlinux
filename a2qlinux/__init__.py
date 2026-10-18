"""A2Qlinux: Questlog Desktop for AION 2 on Linux under Proton, with live game traffic."""

try:
    from ._version import __version__
except ImportError:           # a source checkout that was never built or installed
    __version__ = "0+unknown"
