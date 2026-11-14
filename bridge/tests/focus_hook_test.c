/* focus_hook_test.exe - does a2qlinux/bin/version.dll make IsIconic follow the launcher?
 *
 * Imports VERSION.dll like Questlog.exe (so version.dll beside it is loaded with
 * WINEDLLOVERRIDES=version=n,b). Starts a copy of itself ("focus_hook_test.exe
 * window"), which opens a window and waits - the stand-in for the game's
 * window in another process - and opens a window of its own. Then it asks
 * IsIconic about both the way Questlog does (koffi: LoadLibrary +
 * GetProcAddress) every 100 ms for the given seconds and prints
 * "other iconic yes|no, own iconic yes|no" on every change. Also calls a
 * version.dll function, to show the calls still reach Wine's. Run by the
 * harness in bridge/tests/run_focus_hook_test.py, which switches the bridge's
 * focus state. */
#include <windows.h>
#include <stdio.h>
#include <string.h>

#define OTHER_TITLE L"focus hook test: other process"

static int window_mode(void)
{
    MSG msg;
    CreateWindowExW(0, L"STATIC", OTHER_TITLE, WS_OVERLAPPEDWINDOW | WS_VISIBLE, 0, 0, 200, 100, NULL, NULL, NULL,
                    NULL);
    while (GetMessageW(&msg, NULL, 0, 0) > 0)
        DispatchMessageW(&msg);
    return 0;
}

int main(void)
{
    int argc, seconds = 4, i;
    WCHAR **argv = CommandLineToArgvW(GetCommandLineW(), &argc), self[MAX_PATH], command[MAX_PATH + 16];
    BOOL (WINAPI *iconic)(HWND) = (void *)GetProcAddress(LoadLibraryW(L"user32.dll"), "IsIconic");
    STARTUPINFOW startup;
    PROCESS_INFORMATION child;
    HWND own, other = NULL;
    char last[64] = "", now[64];
    DWORD start, handle;

    if (argc > 1 && !lstrcmpW(argv[1], L"window"))
        ExitProcess(window_mode());
    if (argc > 1)
        seconds = _wtoi(argv[1]);
    memset(&startup, 0, sizeof startup);
    startup.cb = sizeof startup;
    GetModuleFileNameW(NULL, self, MAX_PATH);
    swprintf(command, MAX_PATH + 16, L"\"%ls\" window", self);
    if (!CreateProcessW(self, command, NULL, NULL, FALSE, 0, NULL, NULL, &startup, &child)) {
        printf("could not start the other process (error %lu)\n", GetLastError());
        ExitProcess(1);
    }
    for (i = 0; i < 100 && !other; i++) {
        Sleep(100);
        other = FindWindowW(L"STATIC", OTHER_TITLE);
    }
    if (!other) {
        printf("the other process opened no window\n");
        TerminateProcess(child.hProcess, 1);
        ExitProcess(1);
    }
    own = CreateWindowExW(0, L"STATIC", L"focus hook test", WS_OVERLAPPEDWINDOW | WS_VISIBLE, 0, 0, 200, 100,
                          NULL, NULL, NULL, NULL);
    printf("version.dll answers: %s\n",
           GetFileVersionInfoSizeW(L"C:\\windows\\system32\\kernel32.dll", &handle) ? "yes" : "no");
    fflush(stdout);
    start = GetTickCount();
    while (GetTickCount() - start < (DWORD)seconds * 1000) {
        MSG msg;
        while (PeekMessageW(&msg, NULL, 0, 0, PM_REMOVE))
            DispatchMessageW(&msg);
        snprintf(now, sizeof now, "other iconic %s, own iconic %s", iconic(other) ? "yes" : "no",
                 iconic(own) ? "yes" : "no");
        if (strcmp(now, last)) {
            printf("%.1f s %s\n", (GetTickCount() - start) / 1000.0, now);
            fflush(stdout);
            strcpy(last, now);
        }
        Sleep(100);
    }
    TerminateProcess(child.hProcess, 0);
    ExitProcess(0);   /* returning from the entry point ends only this thread; version.dll has one of its own */
}
