/* questlog_ctl.exe - act on a running Questlog from inside its Wine session.
 *
 * questlog_start.py runs this with protontricks-launch in the game prefix:
 *   questlog_ctl.exe hide-tray     hide Questlog's own tray icon (only that one)
 *   questlog_ctl.exe show-tray     show it again (when our icon is gone)
 *   questlog_ctl.exe close-window  close Questlog's main window (it hides to the tray)
 *   questlog_ctl.exe end-session   tell Questlog the Windows session is ending
 *
 * Questlog's tray icon is replaced by questlog_tray.py: under Wine its menu
 * opens only once, because Electron gives up on the menu when it cannot bring
 * its window to the foreground, and Wine's explorer.exe never grants that
 * (docs/ARCHITECTURE.md §6.2). The icon is hidden with the documented per-icon state NIS_HIDDEN,
 * so the tray icons of other programs in the prefix are untouched. Electron
 * owns it through a hidden window of class Electron_NotifyIconHostWindow and
 * gives its first icon the id kBaseIconId (2) + next_icon_id_ (starts at 1);
 * Questlog has one icon.
 *
 * end-session is what Windows sends at log-off: WM_QUERYENDSESSION, then
 * WM_ENDSESSION. Questlog lets its window close on it, and Electron then ends
 * the browser process at once, without its normal quit. questlog_start.py
 * therefore waits until Questlog has saved before sending it.
 *
 * Questlog's windows are found by program: owned by a process whose image is
 * Questlog.exe. Every outcome is printed; the exit code is 0 on success. */
#include <windows.h>
#include <shellapi.h>
#include <stdio.h>
#include <string.h>

#define ICON_ID 3
#define HIDE_TRAY_WAIT_MS 60000

struct search {
    const WCHAR *class_name;   /* NULL: any class */
    int main_only;             /* visible-or-not top-level window that can be activated */
    HWND found[64];
    int count;
};

static int is_questlog_process(DWORD pid)
{
    WCHAR image[MAX_PATH];
    DWORD size = MAX_PATH;
    const WCHAR *base;
    HANDLE process = OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, FALSE, pid);
    int ok;

    if (!process)
        return 0;
    ok = QueryFullProcessImageNameW(process, 0, image, &size);
    CloseHandle(process);
    if (!ok)
        return 0;
    base = wcsrchr(image, L'\\');
    return lstrcmpiW(base ? base + 1 : image, L"Questlog.exe") == 0;
}

static BOOL CALLBACK collect(HWND w, LPARAM param)
{
    struct search *s = (struct search *)param;
    WCHAR class_name[128];
    DWORD pid = 0;

    if (s->count == (int)(sizeof(s->found) / sizeof(s->found[0])))
        return FALSE;
    GetWindowThreadProcessId(w, &pid);
    if (!pid || !is_questlog_process(pid))
        return TRUE;
    if (s->class_name) {
        if (!GetClassNameW(w, class_name, 128) || wcscmp(class_name, s->class_name))
            return TRUE;
    }
    if (s->main_only) {
        LONG ex = GetWindowLongW(w, GWL_EXSTYLE);
        WCHAR title[64];
        /* The main window: unowned, activatable, not topmost, titled "Questlog".
         * Overlay windows are WS_EX_NOACTIVATE (and owned by the overlay page). */
        if (GetWindow(w, GW_OWNER) || (ex & (WS_EX_NOACTIVATE | WS_EX_TOPMOST | WS_EX_TOOLWINDOW))
            || !GetWindowTextW(w, title, 64) || wcscmp(title, L"Questlog"))
            return TRUE;
    }
    s->found[s->count++] = w;
    return TRUE;
}

static int find(struct search *s, const WCHAR *class_name, int main_only)
{
    memset(s, 0, sizeof(*s));
    s->class_name = class_name;
    s->main_only = main_only;
    EnumWindows(collect, (LPARAM)s);
    return s->count;
}

static int set_tray_hidden(int hidden)
{
    struct search s;
    DWORD waited = 0, limit = hidden ? HIDE_TRAY_WAIT_MS : 0;
    const char *command = hidden ? "hide-tray" : "show-tray";

    for (;;) {
        find(&s, L"Electron_NotifyIconHostWindow", 0);
        for (int i = 0; i < s.count; i++) {
            NOTIFYICONDATAW data;
            memset(&data, 0, sizeof(data));
            data.cbSize = sizeof(data);
            data.hWnd = s.found[i];
            data.uID = ICON_ID;
            data.uFlags = NIF_STATE;
            data.dwState = hidden ? NIS_HIDDEN : 0;
            data.dwStateMask = NIS_HIDDEN;
            if (Shell_NotifyIconW(NIM_MODIFY, &data)) {
                printf("%s: Questlog's tray icon (window %p, id %d) %s.\n", command, (void *)s.found[i], ICON_ID,
                       hidden ? "hidden" : "shown again");
                return 0;
            }
        }
        if (waited >= limit)
            break;
        Sleep(500);
        waited += 500;
    }
    printf("%s: Questlog's tray icon was not found within %lu s (%d icon host windows seen).\n",
           command, limit / 1000, s.count);
    return 1;
}

static int close_window(void)
{
    struct search s;

    if (!find(&s, NULL, 1)) {
        printf("close-window: Questlog's main window was not found.\n");
        return 1;
    }
    for (int i = 0; i < s.count; i++)
        PostMessageW(s.found[i], WM_CLOSE, 0, 0);
    printf("close-window: asked %d Questlog main window(s) to close.\n", s.count);
    return 0;
}

static int end_session(void)
{
    struct search s;
    DWORD_PTR answer = 0;

    if (!find(&s, NULL, 1)) {
        printf("end-session: Questlog's main window was not found.\n");
        return 1;
    }
    /* Electron answers on its main window and then ends the process from
     * WM_ENDSESSION, so the second call is expected to see the window go. */
    if (!SendMessageTimeoutW(s.found[0], WM_QUERYENDSESSION, 0, ENDSESSION_LOGOFF, SMTO_ABORTIFHUNG, 5000, &answer)) {
        printf("end-session: Questlog did not answer the session-end query (error %lu).\n", GetLastError());
        return 1;
    }
    if (!answer) {
        printf("end-session: Questlog refused to end the session.\n");
        return 1;
    }
    SendMessageTimeoutW(s.found[0], WM_ENDSESSION, TRUE, ENDSESSION_LOGOFF, SMTO_ABORTIFHUNG, 5000, &answer);
    printf("end-session: sent to Questlog's main window %p.\n", (void *)s.found[0]);
    return 0;
}

static int run(int argc, WCHAR **argv)
{
    if (argc == 2 && !wcscmp(argv[1], L"hide-tray"))
        return set_tray_hidden(1);
    if (argc == 2 && !wcscmp(argv[1], L"show-tray"))
        return set_tray_hidden(0);
    if (argc == 2 && !wcscmp(argv[1], L"close-window"))
        return close_window();
    if (argc == 2 && !wcscmp(argv[1], L"end-session"))
        return end_session();
    printf("usage: questlog_ctl.exe hide-tray | show-tray | close-window | end-session\n");
    return 2;
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
