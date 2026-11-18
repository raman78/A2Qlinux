#!/usr/bin/env python3
"""Questlog's tray icon, drawn by the desktop instead of by Wine.

Questlog's own tray icon is a Windows icon shown through Wine, and under Wine
its menu opens only once: Electron gives up on the menu when it cannot bring
its window to the foreground, and Wine's explorer.exe never grants that
(docs/ARCHITECTURE.md §6.2). the launcher (a2qlinux/launcher.py) hides that icon and runs this one instead, for
as long as Questlog runs.

This process only reports what was chosen, one word per line on stdout:
    open    left click, or "Open Questlog"
    quit    "Quit Questlog"
the launcher (a2qlinux/launcher.py) does the rest. It ends when its stdin closes, i.e. when
the launcher (a2qlinux/launcher.py) stops it or ends itself.

The launcher tells it, one line on stdin each:
    news <short>\t<full>   news about a newer Questlog (update.update_news): the
                           short text becomes a greyed-out menu line, the full one
                           its tooltip and part of the icon's tooltip
    news                   no news any more; the line goes

With --check it only tells whether it could run here: exit code 0 if Qt
starts and the desktop has a system tray, otherwise 1 with the reason on
stderr (Qt's own message when Qt cannot start). a2qlinux-setup runs it.
"""

import sys

from PyQt6.QtCore import QSocketNotifier
from PyQt6.QtGui import QIcon
from PyQt6.QtWidgets import QApplication, QMenu, QSystemTrayIcon

from a2qlinux import APP_NAME, ICON, shown_version   # ICON is written by a2qlinux-setup


def report(action):
    print(action, flush=True)


def main():
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setDesktopFileName("questlog-aion2")   # setup_desktop.ENTRY_ID
    app.setQuitOnLastWindowClosed(False)
    if not QSystemTrayIcon.isSystemTrayAvailable():
        print("a2qlinux tray: the desktop has no system tray", file=sys.stderr)
        return 1
    if "--check" in sys.argv[1:]:
        return 0

    version = f"A2Qlinux {shown_version()}"
    tray = QSystemTrayIcon(QIcon(str(ICON)), app)
    tray.setToolTip(f"{version} — Questlog for AION 2")
    menu = QMenu()
    menu.addAction(version).setEnabled(False)   # which A2Qlinux runs, for reports; not clickable
    menu.setToolTipsVisible(True)
    news = menu.addAction("")                   # update.update_news, while there is any; not clickable
    news.setEnabled(False)
    news.setVisible(False)
    menu.addSeparator()
    menu.addAction("Open Questlog").triggered.connect(lambda: report("open"))
    menu.addSeparator()
    menu.addAction("Quit Questlog").triggered.connect(lambda: report("quit"))
    tray.setContextMenu(menu)
    tray.activated.connect(lambda reason: reason == QSystemTrayIcon.ActivationReason.Trigger and report("open"))
    tray.show()

    def show_news(line):
        short, _, full = line.removeprefix("news").strip().partition("\t")
        news.setText(short)
        news.setToolTip(full or short)
        news.setVisible(bool(short))
        tray.setToolTip(f"{version} — Questlog for AION 2" + (f"\n{full or short}" if short else ""))

    pending = bytearray()

    def read_launcher():
        data = sys.stdin.buffer.read1(4096)
        if not data:
            app.quit()                          # the launcher stopped us or ended
            return
        pending.extend(data)
        while b"\n" in pending:
            line, _, rest = bytes(pending).partition(b"\n")
            pending[:] = rest
            line = line.decode("utf-8", "replace")
            if line == "news" or line.startswith("news "):
                show_news(line)

    watcher = QSocketNotifier(sys.stdin.fileno(), QSocketNotifier.Type.Read)
    watcher.activated.connect(read_launcher)
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
