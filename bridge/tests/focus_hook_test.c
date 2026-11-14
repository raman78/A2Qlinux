/* focus_hook_test.exe - does a2qlinux/bin/version.dll make GetForegroundWindow follow the launcher?
 *
 * Imports VERSION.dll like Questlog.exe (so version.dll beside it is loaded with
 * WINEDLLOVERRIDES=version=n,b), opens a window of its own and makes it the
 * foreground window, then asks GetForegroundWindow the way Questlog does
 * (koffi: LoadLibrary + GetProcAddress) every 100 ms for the given seconds and
 * prints "own" / "desktop" / "other" on every change. Also calls a version.dll
 * function, to show the calls still reach Wine's. Run by the harness in
 * bridge/tests/run_focus_hook_test.py, which switches the bridge's focus state. */
#include <windows.h>
#include <stdio.h>

int main(void)
{
    int argc, seconds = 4;
    WCHAR **argv = CommandLineToArgvW(GetCommandLineW(), &argc);
    HWND (WINAPI *foreground)(void) = (void *)GetProcAddress(LoadLibraryW(L"user32.dll"), "GetForegroundWindow");
    HWND own = CreateWindowExW(0, L"STATIC", L"focus hook test", WS_OVERLAPPEDWINDOW | WS_VISIBLE, 0, 0, 200, 100,
                               NULL, NULL, NULL, NULL);
    const char *last = "";
    DWORD start = GetTickCount(), handle;

    if (argc > 1)
        seconds = _wtoi(argv[1]);
    SetForegroundWindow(own);
    printf("version.dll answers: %s\n",
           GetFileVersionInfoSizeW(L"C:\\windows\\system32\\kernel32.dll", &handle) ? "yes" : "no");
    while (GetTickCount() - start < (DWORD)seconds * 1000) {
        MSG msg;
        HWND w = foreground();
        const char *now = w == own ? "own" : w == GetDesktopWindow() ? "desktop" : "other";
        while (PeekMessageW(&msg, NULL, 0, 0, PM_REMOVE))
            DispatchMessageW(&msg);
        if (strcmp(now, last)) {
            printf("%.1f s %s\n", (GetTickCount() - start) / 1000.0, now);
            fflush(stdout);
            last = now;
        }
        Sleep(100);
    }
    ExitProcess(0);   /* returning from the entry point ends only this thread; version.dll has one of its own */
}
