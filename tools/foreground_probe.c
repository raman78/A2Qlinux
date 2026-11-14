/* foreground_probe.exe [seconds] - Wine's foreground window and Questlog's overlays, twice a second.
 *
 * Questlog makes its overlays topmost while the game's window is the
 * foreground window (GetForegroundWindow, polled every 100 ms in its main
 * process) and lowers them in the window order otherwise (docs/ARCHITECTURE.md
 * §6.12). This prints Wine's answer - unchanged by A2Qlinux's version.dll,
 * which acts in Questlog's process only - and what became of the overlays, so
 * one can switch between the game and a Linux program while it runs and see
 * what Wine and Questlog do (issue #3). Read only: it changes nothing.
 *
 * Run in the game prefix:  protontricks-launch --appid 3393110 tools/foreground_probe.exe 20
 * Each line: seconds since start, the window handle, its process id and
 * program, class and title ("(none)" when there is no foreground window);
 * whether the game's window (class UnrealWindow) is topmost; how many of
 * Questlog's overlay windows are visible and how many of them topmost. A
 * line is printed only when something changes, plus one at the start. */
#include <windows.h>
#include <stdio.h>
#include <string.h>

static void describe(HWND w, char *out, size_t size)
{
    DWORD pid = 0;
    WCHAR image[MAX_PATH] = L"?", cls[128] = L"", title[128] = L"";
    DWORD len = MAX_PATH;
    const WCHAR *base;
    HANDLE process;

    if (!w) {
        snprintf(out, size, "(none)");
        return;
    }
    GetWindowThreadProcessId(w, &pid);
    process = OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, FALSE, pid);
    if (process) {
        if (!QueryFullProcessImageNameW(process, 0, image, &len))
            lstrcpyW(image, L"?");
        CloseHandle(process);
    }
    base = wcsrchr(image, L'\\');
    GetClassNameW(w, cls, 128);
    GetWindowTextW(w, title, 128);
    snprintf(out, size, "%p pid %lu %ls class \"%ls\" title \"%ls\"", (void *)w, pid,
             base ? base + 1 : image, cls, title);
}

struct overlay_count { int all, topmost; HWND game; };

/* Questlog's overlays: windows with WS_EX_NOACTIVATE | WS_EX_LAYERED | WS_EX_TRANSPARENT (docs §6.1),
 * whose program is Questlog.exe; the game's main window: class UnrealWindow. */
static BOOL CALLBACK count_windows(HWND w, LPARAM param)
{
    struct overlay_count *c = (struct overlay_count *)param;
    LONG ex = GetWindowLongW(w, GWL_EXSTYLE);
    WCHAR cls[64] = L"";
    GetClassNameW(w, cls, 64);
    if (!lstrcmpW(cls, L"UnrealWindow") && IsWindowVisible(w))
        c->game = w;
    if (IsWindowVisible(w) && (ex & 0x08080020) == 0x08080020) {
        c->all++;
        if (ex & WS_EX_TOPMOST)
            c->topmost++;
    }
    return TRUE;
}

int main(void)
{
    int argc, seconds = 20;
    WCHAR **argv = CommandLineToArgvW(GetCommandLineW(), &argc);
    char last[1024] = "", now[1024];
    DWORD start = GetTickCount();

    if (argc > 1)
        seconds = _wtoi(argv[1]);
    while (GetTickCount() - start < (DWORD)seconds * 1000) {
        struct overlay_count c = {0, 0, NULL};
        char extra[128];
        EnumWindows(count_windows, (LPARAM)&c);
        describe(GetForegroundWindow(), now, sizeof now);
        snprintf(extra, sizeof extra, " | game topmost %s | overlays %d, topmost %d",
                 c.game ? ((GetWindowLongW(c.game, GWL_EXSTYLE) & WS_EX_TOPMOST) ? "yes" : "no") : "?",
                 c.all, c.topmost);
        strncat(now, extra, sizeof now - strlen(now) - 1);
        if (strcmp(now, last)) {
            printf("%5.1f s  %s\n", (GetTickCount() - start) / 1000.0, now);
            fflush(stdout);
            strcpy(last, now);
        }
        Sleep(500);
    }
    printf("%5.1f s  done\n", (GetTickCount() - start) / 1000.0);
    fflush(stdout);
    return 0;
}
