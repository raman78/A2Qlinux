"""Whether the desktop's active window is one of Wine's, for Questlog's overlays (docs/ARCHITECTURE.md §6.12).

Questlog shows its overlays while the game is Windows' foreground window
and hides them otherwise. Under Wine that answer goes stale on a Linux
desktop: when a Linux program becomes active, Wine keeps the game as its
foreground window, and Questlog's overlays stay above the Linux program.
X11 itself does know: the window manager - KWin, Mutter or any other, also
for Xwayland - moves _NET_ACTIVE_WINDOW on the root window (EWMH) to a
window of its own when a Wayland or other non-Wine window becomes active.

ActiveWindowWatch follows that property with Xlib (through ctypes: libX11
is there wherever Wine's X11 driver runs) and reports "in" while a Wine
window is active and "out" otherwise. It runs in a child process of the
launcher (`python -m a2qlinux.focus`, FocusFollower), because Xlib ends the
whole process when its display connection is lost - as when Xwayland goes
down with the desktop session - and the launcher must outlive that. The
launcher passes the state to
version.dll in Questlog's main process over the capture bridge
(BridgeServer.set_focus), which then answers Questlog's GetForegroundWindow
with the desktop window while it is "out". Nothing is changed on the X side:
the watch only reads.
"""

import ctypes
import ctypes.util
import os
import subprocess
import sys
import threading

IN, OUT = "in", "out"
PROPERTY_CHANGE_MASK = 1 << 22
PROPERTY_NOTIFY = 28
XA_WINDOW = 33


def is_wine_class(wm_class):
    """Whether a WM_CLASS (res_name, res_class) is a Wine window's.

    Proton names the game's windows steam_app_<appid> and those of other
    programs in the prefix (Questlog, its overlays) steam_proton; plain Wine
    names them after the program, e.g. questlog.exe.
    """
    for part in wm_class:
        part = (part or "").lower()
        if part.startswith("steam_app_") or part == "steam_proton" or part.endswith(".exe"):
            return True
    return False


class _XPropertyEvent(ctypes.Structure):
    _fields_ = [("type", ctypes.c_int), ("serial", ctypes.c_ulong), ("send_event", ctypes.c_int),
                ("display", ctypes.c_void_p), ("window", ctypes.c_ulong), ("atom", ctypes.c_ulong),
                ("time", ctypes.c_ulong), ("state", ctypes.c_int)]


class _XEvent(ctypes.Union):
    _fields_ = [("type", ctypes.c_int), ("xproperty", _XPropertyEvent), ("pad", ctypes.c_long * 24)]


class _XClassHint(ctypes.Structure):
    _fields_ = [("res_name", ctypes.c_void_p), ("res_class", ctypes.c_void_p)]   # freed with XFree


_ERROR_HANDLER = ctypes.CFUNCTYPE(ctypes.c_int, ctypes.c_void_p, ctypes.c_void_p)


class ActiveWindowWatch:
    """Call on_change(IN | OUT) now and on every change of the desktop's active window's kind.

    start() returns None when it runs, else the reason it cannot (no DISPLAY,
    no libX11, no display connection); the caller logs that once, and
    Questlog's overlays then follow Wine's foreground window as before.
    """

    def __init__(self, on_change, display=None):
        self.on_change = on_change
        self.display_name = display if display is not None else os.environ.get("DISPLAY", "")
        self.state = None

    def start(self):
        if not self.display_name:
            return "no X display (DISPLAY is not set)"
        path = ctypes.util.find_library("X11")
        if not path:
            return "libX11 was not found"
        x = ctypes.CDLL(path)
        x.XOpenDisplay.restype = ctypes.c_void_p
        x.XOpenDisplay.argtypes = [ctypes.c_char_p]
        display = x.XOpenDisplay(self.display_name.encode())
        if not display:
            return f"the X display {self.display_name} could not be opened"
        self._x, self._display = x, ctypes.c_void_p(display)
        for name, args, result in (
                ("XDefaultRootWindow", [ctypes.c_void_p], ctypes.c_ulong),
                ("XInternAtom", [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_int], ctypes.c_ulong),
                ("XSelectInput", [ctypes.c_void_p, ctypes.c_ulong, ctypes.c_long], ctypes.c_int),
                ("XNextEvent", [ctypes.c_void_p, ctypes.c_void_p], ctypes.c_int),
                ("XGetWindowProperty", [ctypes.c_void_p, ctypes.c_ulong, ctypes.c_ulong, ctypes.c_long,
                                        ctypes.c_long, ctypes.c_int, ctypes.c_ulong,
                                        ctypes.POINTER(ctypes.c_ulong), ctypes.POINTER(ctypes.c_int),
                                        ctypes.POINTER(ctypes.c_ulong), ctypes.POINTER(ctypes.c_ulong),
                                        ctypes.POINTER(ctypes.c_void_p)], ctypes.c_int),
                ("XGetClassHint", [ctypes.c_void_p, ctypes.c_ulong, ctypes.POINTER(_XClassHint)], ctypes.c_int),
                ("XFree", [ctypes.c_void_p], ctypes.c_int),
                ("XSetErrorHandler", [_ERROR_HANDLER], ctypes.c_void_p)):
            getattr(x, name).argtypes, getattr(x, name).restype = args, result
        # A window can go away between reading the property and asking its class;
        # Xlib's default handler would end the launcher for that.
        self._ignore_errors = _ERROR_HANDLER(lambda display, event: 0)
        x.XSetErrorHandler(self._ignore_errors)
        self._root = x.XDefaultRootWindow(self._display)
        self._atom = x.XInternAtom(self._display, b"_NET_ACTIVE_WINDOW", 0)
        x.XSelectInput(self._display, self._root, PROPERTY_CHANGE_MASK)
        self._update()
        threading.Thread(target=self._loop, daemon=True, name="active-window").start()
        return None

    def _active_window(self):
        kind, fmt = ctypes.c_ulong(), ctypes.c_int()
        count, after, data = ctypes.c_ulong(), ctypes.c_ulong(), ctypes.c_void_p()
        if self._x.XGetWindowProperty(self._display, self._root, self._atom, 0, 1, 0, XA_WINDOW,
                                      ctypes.byref(kind), ctypes.byref(fmt), ctypes.byref(count),
                                      ctypes.byref(after), ctypes.byref(data)) != 0 or not data.value:
            return 0
        try:
            return ctypes.cast(data, ctypes.POINTER(ctypes.c_ulong))[0] if count.value else 0
        finally:
            self._x.XFree(data)

    def _wm_class(self, window):
        hint = _XClassHint()
        if not window or not self._x.XGetClassHint(self._display, window, ctypes.byref(hint)):
            return ("", "")
        names = tuple(ctypes.string_at(value).decode("utf-8", "replace") if value else ""
                      for value in (hint.res_name, hint.res_class))
        for value in (hint.res_name, hint.res_class):
            if value:
                self._x.XFree(ctypes.c_void_p(value))
        return names

    def _update(self):
        state = IN if is_wine_class(self._wm_class(self._active_window())) else OUT
        if state != self.state:
            self.state = state
            self.on_change(state)

    def _loop(self):
        event = _XEvent()
        while True:
            self._x.XNextEvent(self._display, ctypes.byref(event))
            if event.type == PROPERTY_NOTIFY and event.xproperty.atom == self._atom:
                self._update()


def main():
    """Child process: print "in"/"out" on every change; a reason on stderr and exit code 2 if it cannot run."""
    watch = ActiveWindowWatch(lambda state: print(state, flush=True))
    why_not = watch.start()
    if why_not:
        print(why_not, file=sys.stderr, flush=True)
        return 2
    threading.Event().wait()
    return 0


class FocusFollower:
    """Runs `python -m a2qlinux.focus` and passes each line to on_change; the launcher's side.

    When the child cannot start watching, or ends (the X display went away),
    the reason is logged, on_change gets "in" - Questlog's overlays then
    follow Wine's foreground window as before - and the child is started
    again after RESTART_WAIT seconds, in case the display comes back.
    """

    RESTART_WAIT = 30

    def __init__(self, on_change, log, command=None):
        self.on_change, self.log = on_change, log
        self.command = command or [sys.executable, "-m", "a2qlinux.focus"]
        self.stopped = threading.Event()
        self.process = None

    def start(self):
        threading.Thread(target=self._run, daemon=True, name="focus-follower").start()

    def _run(self):
        told = None
        while not self.stopped.is_set():
            try:
                self.process = subprocess.Popen(self.command, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                                stderr=subprocess.PIPE, text=True)
            except OSError as error:
                reason = str(error)
            else:
                for line in self.process.stdout:
                    if line.strip() in (IN, OUT):
                        self.on_change(line.strip())
                code = self.process.wait()
                reason = self.process.stderr.read().strip().splitlines()
                reason = reason[-1] if reason else f"it ended with code {code}"
            self.on_change(IN)
            if self.stopped.is_set():
                return
            if reason != told:              # once per distinct reason, not on every restart
                self.log(f"Cannot follow the desktop's active window ({reason}); Questlog's overlays stay over "
                         f"other programs when the game is not in front. Trying again every {self.RESTART_WAIT} s.")
                told = reason
            self.stopped.wait(self.RESTART_WAIT)

    def stop(self):
        self.stopped.set()
        if self.process and self.process.poll() is None:
            self.process.terminate()


if __name__ == "__main__":
    sys.exit(main())
