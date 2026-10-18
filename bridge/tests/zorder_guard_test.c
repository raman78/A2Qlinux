/* Test for wpcap.dll's window-order guard; run in a throwaway prefix:
 *   zorder_guard_test.exe <path to wpcap.dll>
 *
 * It rebuilds the state behind the bug the guard exists for: a game window in
 * the foreground with Questlog's main window above it in Wine's z-order.
 *   - a second copy of this program ("questlog" role, same image as the test,
 *     like Questlog's browser process next to the utility process that loads
 *     the DLL) owns an ordinary window and an overlay-like window
 *     (WS_EX_NOACTIVATE);
 *   - a copy of this program under another name ("game" role) owns the
 *     foreground window.
 * The test lifts both Questlog windows above the game without activating them,
 * loads the DLL, calls pcap_findalldevs (which starts the guard) and checks
 * after 500 ms that the ordinary window is below the game, the overlay window
 * still above it, and the game still in the foreground. Exit code 0 = pass. */
#include <windows.h>
#include <shellapi.h>
#include <stdio.h>
#include <string.h>

#define CLASS_NAME L"ZorderGuardTest"

static LRESULT CALLBACK proc(HWND w, UINT m, WPARAM wp, LPARAM lp)
{
    return DefWindowProcW(w, m, wp, lp);
}

static HWND make_window(const WCHAR *title, DWORD ex_style)
{
    WNDCLASSW wc = {0};
    HWND w;
    wc.lpfnWndProc = proc;
    wc.hInstance = GetModuleHandleW(NULL);
    wc.lpszClassName = CLASS_NAME;
    RegisterClassW(&wc);
    w = CreateWindowExW(ex_style, CLASS_NAME, title, WS_POPUP | WS_VISIBLE, 0, 0, 800, 600,
                        NULL, NULL, wc.hInstance, NULL);
    return w;
}

static int serve(const WCHAR *role)
{
    MSG m;
    if (!wcscmp(role, L"game")) {
        HWND g = make_window(L"zg-game", 0);
        SetForegroundWindow(g);
    } else {
        make_window(L"zg-questlog", 0);
        make_window(L"zg-overlay", WS_EX_NOACTIVATE);
    }
    while (GetMessageW(&m, NULL, 0, 0) > 0) {
        TranslateMessage(&m);
        DispatchMessageW(&m);
    }
    return 0;
}

static HANDLE spawn(const WCHAR *exe, const WCHAR *role)
{
    WCHAR cmd[2 * MAX_PATH];
    STARTUPINFOW si = {0};
    PROCESS_INFORMATION pi;
    si.cb = sizeof(si);
    swprintf(cmd, 2 * MAX_PATH, L"\"%ls\" --serve %ls", exe, role);
    if (!CreateProcessW(exe, cmd, NULL, NULL, FALSE, 0, NULL, NULL, &si, &pi))
        return NULL;
    CloseHandle(pi.hThread);
    return pi.hProcess;
}

static HWND wait_window(const WCHAR *title)
{
    HWND w = NULL;
    for (int i = 0; i < 100 && !(w = FindWindowW(CLASS_NAME, title)); i++)
        Sleep(50);
    return w;
}

/* 1 if a is above b in the z-order. */
static int above(HWND a, HWND b)
{
    for (HWND w = GetWindow(b, GW_HWNDPREV); w; w = GetWindow(w, GW_HWNDPREV))
        if (w == a)
            return 1;
    return 0;
}

static int run(int argc, WCHAR **argv)
{
    WCHAR self[MAX_PATH], game_exe[MAX_PATH];
    HANDLE questlog_proc, game_proc;
    HWND q, o, g;
    HMODULE dll;
    void *devs;
    char err[256];
    int (*findalldevs)(void **, char *);
    int ok = 1;

    if (argc == 3 && !wcscmp(argv[1], L"--serve"))
        return serve(argv[2]);
    if (argc != 2) {
        printf("usage: zorder_guard_test.exe <wpcap.dll>\n");
        return 2;
    }

    GetModuleFileNameW(NULL, self, MAX_PATH);
    wcscpy(game_exe, self);
    wcscpy(wcsrchr(game_exe, L'\\') + 1, L"zg_game.exe");
    if (!CopyFileW(self, game_exe, FALSE)) {
        printf("FAIL: cannot copy the test as the game program (error %lu)\n", GetLastError());
        return 1;
    }
    questlog_proc = spawn(self, L"questlog");
    q = wait_window(L"zg-questlog");
    o = wait_window(L"zg-overlay");
    game_proc = spawn(game_exe, L"game");
    g = wait_window(L"zg-game");
    if (!q || !o || !g) {
        printf("FAIL: test windows did not appear (questlog %p, overlay %p, game %p)\n", q, o, g);
        return 1;
    }
    Sleep(300);

    /* The bug's state: game in the foreground, Questlog's windows above it. */
    SetWindowPos(q, HWND_TOP, 0, 0, 0, 0, SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE);
    SetWindowPos(o, HWND_TOP, 0, 0, 0, 0, SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE);
    printf("before: foreground is game %d, questlog above game %d, overlay above game %d\n",
           GetForegroundWindow() == g, above(q, g), above(o, g));
    if (GetForegroundWindow() != g || !above(q, g) || !above(o, g)) {
        printf("FAIL: could not set up the starting state\n");
        ok = 0;
    } else {
        if (!(dll = LoadLibraryW(argv[1]))
            || !(findalldevs = (int (*)(void **, char *))GetProcAddress(dll, "pcap_findalldevs"))) {
            printf("FAIL: cannot load %ls\n", argv[1]);
            ok = 0;
        } else {
            findalldevs(&devs, err);   /* no bridge configured: fails, but starts the guard */
            Sleep(500);
            printf("after:  foreground is game %d, questlog above game %d, overlay above game %d\n",
                   GetForegroundWindow() == g, above(q, g), above(o, g));
            ok = GetForegroundWindow() == g && !above(q, g) && above(o, g);
        }
    }
    TerminateProcess(questlog_proc, 0);
    TerminateProcess(game_proc, 0);
    WaitForSingleObject(game_proc, 2000);
    DeleteFileW(game_exe);
    printf("%s\n", ok ? "PASS" : "FAIL");
    return ok ? 0 : 1;
}

/* Entry point (built with -nostdlib): arguments come from the command line. */
void start(void)
{
    int argc;
    WCHAR **argv = CommandLineToArgvW(GetCommandLineW(), &argc);
    int code = run(argc, argv);
    fflush(stdout);
    ExitProcess(code);
}
