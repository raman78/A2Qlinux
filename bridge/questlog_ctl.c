/* questlog_ctl.exe - act on a running Questlog from inside its Wine session.
 *
 * The launcher (a2qlinux/launcher.py) runs this with protontricks-launch in the game prefix:
 *   questlog_ctl.exe hide-tray     hide Questlog's own tray icon (only that one)
 *   questlog_ctl.exe show-tray     show it again (when our icon is gone)
 *   questlog_ctl.exe close-window  close Questlog's main window (what follows is Questlog's closeAction setting)
 *   questlog_ctl.exe end-session   tell Questlog the Windows session is ending
 *   questlog_ctl.exe folder-handler status|set|remove
 *                                  the prefix's handler for opening a folder (a2qlinux/open_folders.py)
 *
 * Questlog's tray icon is replaced by a2qlinux/tray.py: under Wine its menu
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
 * the browser process at once, without its normal quit. the launcher
 * therefore waits until Questlog has saved before sending it.
 *
 * close-window posts WM_CLOSE, which Questlog treats as a click on the
 * window's X: its closeAction setting decides - "tray" hides the window,
 * "quit" quits Questlog normally, "ask" (the default) asks which.
 *
 * folder-handler: Questlog's "Open Folder" buttons call Electron's
 * shell.openPath, which asks ShellExecuteEx for the verb "explore" of the
 * class "folder". Wine's prefix has no command for that verb, so the call
 * fails with "There is no Windows program configured to open this type of
 * file". `set` writes the command Wine uses for web links (winebrowser.exe,
 * which hands the folder to xdg-open) as HKLM\Software\Classes\folder\shell\
 * explore\command - only if that command is absent; `remove` deletes it only
 * if it still holds exactly what `set` wrote (docs/ARCHITECTURE.md §6.10).
 * The first word printed is the outcome: absent, ours, other, set, removed.
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

#define HANDLER_KEY L"Software\\Classes\\folder\\shell\\explore\\command"
#define HANDLER_PARENT L"Software\\Classes\\folder\\shell"
#define HANDLER_VERB L"explore"
#define HANDLER_VALUE L"\"C:\\windows\\system32\\winebrowser.exe\" \"%1\""

/* The handler's default value: 0 absent, 1 ours, 2 something else (in `value`), -1 error. */
static int read_handler(WCHAR *value, DWORD size)
{
    HKEY key;
    DWORD type = 0, bytes = size * sizeof(WCHAR);
    LONG status = RegOpenKeyExW(HKEY_LOCAL_MACHINE, HANDLER_KEY, 0, KEY_QUERY_VALUE, &key);

    value[0] = 0;
    if (status == ERROR_FILE_NOT_FOUND)
        return 0;
    if (status != ERROR_SUCCESS) {
        printf("error: HKLM\\%ls could not be opened (error %ld).\n", HANDLER_KEY, status);
        return -1;
    }
    status = RegQueryValueExW(key, NULL, NULL, &type, (BYTE *)value, &bytes);
    RegCloseKey(key);
    if (status == ERROR_FILE_NOT_FOUND)
        return 2;                       /* a key without a default value is someone else's too */
    if (status != ERROR_SUCCESS) {
        printf("error: HKLM\\%ls could not be read (error %ld).\n", HANDLER_KEY, status);
        return -1;
    }
    value[size - 1] = 0;
    return (type == REG_SZ || type == REG_EXPAND_SZ) && !wcscmp(value, HANDLER_VALUE) ? 1 : 2;
}

static int folder_handler(const WCHAR *action)
{
    WCHAR value[512];
    int state = read_handler(value, 512);
    HKEY key;
    LONG status;

    if (state < 0)
        return 1;
    if (!wcscmp(action, L"status")) {
        if (state == 0)
            printf("absent: no command opens folders for \"explore\".\n");
        else if (state == 1)
            printf("ours: folders open through winebrowser.exe (%ls).\n", HANDLER_VALUE);
        else
            printf("other: HKLM\\%ls holds %ls; left as it is.\n", HANDLER_KEY, value[0] ? value : L"no command");
        return 0;
    }
    if (!wcscmp(action, L"set")) {
        if (state == 1) {
            printf("ours: folders already open through winebrowser.exe.\n");
            return 0;
        }
        if (state == 2) {
            printf("other: HKLM\\%ls holds %ls; left as it is.\n", HANDLER_KEY, value[0] ? value : L"no command");
            return 0;
        }
        status = RegCreateKeyExW(HKEY_LOCAL_MACHINE, HANDLER_KEY, 0, NULL, 0, KEY_SET_VALUE, NULL, &key, NULL);
        if (status == ERROR_SUCCESS) {
            status = RegSetValueExW(key, NULL, 0, REG_SZ, (const BYTE *)HANDLER_VALUE, sizeof(HANDLER_VALUE));
            RegCloseKey(key);
        }
        if (status != ERROR_SUCCESS) {
            printf("error: HKLM\\%ls could not be written (error %ld).\n", HANDLER_KEY, status);
            return 1;
        }
        printf("set: folders now open through winebrowser.exe (%ls).\n", HANDLER_VALUE);
        return 0;
    }
    /* remove */
    if (state != 1) {
        if (state == 0)
            printf("absent: nothing to remove.\n");
        else
            printf("other: HKLM\\%ls holds %ls, not what set wrote; left as it is.\n", HANDLER_KEY,
                   value[0] ? value : L"no command");
        return 0;
    }
    /* `command`, then the verb's key `explore` if nothing else is left in it
     * (set made both; anything added there since is someone else's). */
    status = RegOpenKeyExW(HKEY_LOCAL_MACHINE, HANDLER_PARENT L"\\" HANDLER_VERB, 0, KEY_ALL_ACCESS, &key);
    if (status == ERROR_SUCCESS) {
        DWORD subkeys = 1, values = 1;
        status = RegDeleteKeyW(key, L"command");
        if (status == ERROR_SUCCESS && RegQueryInfoKeyW(key, NULL, NULL, NULL, &subkeys, NULL, NULL, &values,
                                                        NULL, NULL, NULL, NULL) == ERROR_SUCCESS
            && !subkeys && !values) {
            HKEY parent;
            if (RegOpenKeyExW(HKEY_LOCAL_MACHINE, HANDLER_PARENT, 0, KEY_ALL_ACCESS, &parent) == ERROR_SUCCESS) {
                RegDeleteKeyW(parent, HANDLER_VERB);
                RegCloseKey(parent);
            }
        }
        RegCloseKey(key);
    }
    if (status != ERROR_SUCCESS) {
        printf("error: HKLM\\%ls could not be removed (error %ld).\n", HANDLER_KEY, status);
        return 1;
    }
    printf("removed: HKLM\\%ls.\n", HANDLER_KEY);
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
    if (argc == 3 && !wcscmp(argv[1], L"folder-handler")
        && (!wcscmp(argv[2], L"status") || !wcscmp(argv[2], L"set") || !wcscmp(argv[2], L"remove")))
        return folder_handler(argv[2]);
    printf("usage: questlog_ctl.exe hide-tray | show-tray | close-window | end-session"
           " | folder-handler status|set|remove\n");
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
