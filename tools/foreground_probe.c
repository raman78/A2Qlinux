/* foreground_probe.exe [seconds] - what Wine reports as the foreground window, twice a second.
 *
 * Questlog shows its overlays while the game's window is the foreground
 * window (GetForegroundWindow, polled every 100 ms in its main process) and
 * hides them otherwise. This prints the same answer Questlog gets, so one can
 * switch between the game and a Linux program while it runs and see whether
 * Wine's foreground follows (issue #3). Read only: it changes nothing.
 *
 * Run in the game prefix:  protontricks-launch --appid 3393110 tools/foreground_probe.exe 20
 * Each line: seconds since start, the window handle, its process id and
 * program, class and title; "(none)" when there is no foreground window. A
 * line is printed only when the answer changes, plus one at the start. */
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

int main(void)
{
    int argc, seconds = 20;
    WCHAR **argv = CommandLineToArgvW(GetCommandLineW(), &argc);
    char last[1024] = "", now[1024];
    DWORD start = GetTickCount();

    if (argc > 1)
        seconds = _wtoi(argv[1]);
    while (GetTickCount() - start < (DWORD)seconds * 1000) {
        describe(GetForegroundWindow(), now, sizeof now);
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
