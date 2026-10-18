#!/usr/bin/env python3
"""Questlog's tray icon, drawn by KDE instead of by Wine.

Questlog's own tray icon is a Windows icon shown through Wine, and under Wine
its menu opens only once: Electron gives up on the menu when it cannot bring
its window to the foreground, and Wine's explorer.exe never grants that
(docs/ARCHITECTURE.md §6.2). questlog_start.py hides that icon and runs this one instead, for
as long as Questlog runs.

This process only reports what was chosen, one word per line on stdout:
    open    left click, or "Open Questlog"
    quit    "Quit Questlog"
questlog_start.py does the rest. It ends when its stdin closes, i.e. when
questlog_start.py stops it or ends itself.
"""

from pathlib import Path
import sys

from PyQt6.QtCore import QSocketNotifier
from PyQt6.QtGui import QIcon
from PyQt6.QtWidgets import QApplication, QMenu, QSystemTrayIcon

ICON = Path.home() / ".local" / "share" / "icons" / "questlog-aion2.png"   # written by install.py


def report(action):
    print(action, flush=True)


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("Questlog (AION 2)")
    app.setDesktopFileName("questlog-aion2")
    app.setQuitOnLastWindowClosed(False)
    if not QSystemTrayIcon.isSystemTrayAvailable():
        print("questlog_tray: the desktop has no system tray", file=sys.stderr)
        return 1

    tray = QSystemTrayIcon(QIcon(str(ICON)), app)
    tray.setToolTip("Questlog (AION 2)")
    menu = QMenu()
    menu.addAction("Open Questlog").triggered.connect(lambda: report("open"))
    menu.addSeparator()
    menu.addAction("Quit Questlog").triggered.connect(lambda: report("quit"))
    tray.setContextMenu(menu)
    tray.activated.connect(lambda reason: reason == QSystemTrayIcon.ActivationReason.Trigger and report("open"))
    tray.show()

    def parent_gone():
        if not sys.stdin.buffer.read1(4096):
            app.quit()

    watcher = QSocketNotifier(sys.stdin.fileno(), QSocketNotifier.Type.Read)
    watcher.activated.connect(parent_gone)
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
