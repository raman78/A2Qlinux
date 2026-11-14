/* version.dll - tells Questlog the game is minimized while the desktop's active window is not one of Wine's.
 *
 * Questlog places its overlays (meter, timers, tracker, map, Black Market
 * Cards) above the game while the game is in front; when another window is
 * in front it only lowers them beneath it in the window order, and it hides
 * them altogether when the game's window is minimized (IsIconic, asked every
 * 100 ms in its main process: "hud hidden, game window minimized or empty").
 * Under Wine on a Linux desktop the lowering has no effect: the overlays are
 * unmanaged (override-redirect) X windows, which the compositor draws above
 * every window that is not Wine's, whatever their order inside Wine. So they
 * stay over a browser or terminal (docs/ARCHITECTURE.md §6.12, issue #3).
 * The launcher follows the desktop's active window through X11 and passes
 * "in" (a Wine window is active) or "out" (anything else) over the capture
 * bridge; while it is "out", this DLL's IsIconic answers yes for windows of
 * other processes - the game's - so Questlog hides its overlays by its own
 * logic, and shows them again by it once a Wine window is active. Nothing
 * else changes: the game and the other programs in the prefix are not touched
 * and Questlog's own windows always get the real answer.
 *
 * How it gets into Questlog's main process: Questlog.exe imports VERSION.dll,
 * so a version.dll beside it, with WINEDLLOVERRIDES=version=n,b in Questlog's
 * environment only, is loaded instead of Wine's. It passes every one of
 * version.dll's 16 functions on to the real one in system32. Only in the main
 * process (no --type= on its command line) and only when Questlog was started
 * by A2Qlinux (QUESTLOG_PROTON_BRIDGE set) does it replace user32's IsIconic:
 * the first 12 bytes become a jump to fake_iconic, written while version.dll
 * is loaded, when Questlog's other threads do not exist yet. Questlog calls
 * user32 through koffi, which looks the function up with GetProcAddress, so
 * only a replacement of the function itself reaches it. The replacement is
 * refused, and logged, when user32's export table shows less than 12 bytes
 * before the next exported function (Wine 9 to 11 and Proton have 48).
 *
 * Without the launcher (no connection) every answer is the real one. Lines in
 * Questlog's log (proton-stream/questlog.log) start with "[a2qlinux] focus". */
#include <winsock2.h>
#include <windows.h>
#include <stdarg.h>
#include <stdio.h>
#include <string.h>

#define HOOK_SIGNATURE "a2qlinux focus hook"
#define PATCH_BYTES 12
#define RETRY_MS 2000

static const char signature[] = HOOK_SIGNATURE;   /* the launcher recognises its own file by it */

/* ---------------------------------------------------------------- version.dll's functions */

static const char *const names[16] = {
    "GetFileVersionInfoA", "GetFileVersionInfoExA", "GetFileVersionInfoExW", "GetFileVersionInfoSizeA",
    "GetFileVersionInfoSizeExA", "GetFileVersionInfoSizeExW", "GetFileVersionInfoSizeW", "GetFileVersionInfoW",
    "VerFindFileA", "VerFindFileW", "VerInstallFileA", "VerInstallFileW", "VerLanguageNameA",
    "VerLanguageNameW", "VerQueryValueA", "VerQueryValueW"};
FARPROC forward[16];

/* Each export jumps to the real function with its arguments untouched (focus_hook.def names them). */
#define PASS(i, name) __attribute__((naked)) void pass_##name(void) { __asm__("jmp *%0" :: "m"(forward[i])); }
PASS(0, GetFileVersionInfoA) PASS(1, GetFileVersionInfoExA) PASS(2, GetFileVersionInfoExW)
PASS(3, GetFileVersionInfoSizeA) PASS(4, GetFileVersionInfoSizeExA) PASS(5, GetFileVersionInfoSizeExW)
PASS(6, GetFileVersionInfoSizeW) PASS(7, GetFileVersionInfoW) PASS(8, VerFindFileA) PASS(9, VerFindFileW)
PASS(10, VerInstallFileA) PASS(11, VerInstallFileW) PASS(12, VerLanguageNameA) PASS(13, VerLanguageNameW)
PASS(14, VerQueryValueA) PASS(15, VerQueryValueW)

static void focus_log(const char *fmt, ...)
{
    char line[400];
    va_list args;
    va_start(args, fmt);
    vsnprintf(line, sizeof line, fmt, args);
    va_end(args);
    fprintf(stderr, "[a2qlinux] focus: %s\n", line);
    fflush(stderr);
}

static int load_real_version(void)
{
    WCHAR path[MAX_PATH];
    HMODULE real;
    int i;
    UINT n = GetSystemDirectoryW(path, MAX_PATH - 16);
    if (!n || n >= MAX_PATH - 16)
        return 0;
    lstrcatW(path, L"\\version.dll");
    real = LoadLibraryW(path);
    if (!real)
        return 0;
    for (i = 0; i < 16; i++)
        forward[i] = GetProcAddress(real, names[i]);
    return 1;
}

/* ---------------------------------------------------------------- the replacement */

static volatile LONG outside;                 /* 1 while the desktop's active window is not Wine's */

/* IsIconic as Windows and Wine define it (WS_MINIMIZE in the window's style),
 * except that a window of another process counts as minimized while "out". */
static BOOL WINAPI fake_iconic(HWND window)
{
    DWORD pid = 0;
    if (outside && window && GetWindowThreadProcessId(window, &pid) && pid && pid != GetCurrentProcessId())
        return TRUE;
    return (GetWindowLongW(window, GWL_STYLE) & WS_MINIMIZE) != 0;
}

/* Bytes from `target` to the next exported function of `module`: how much may be overwritten. */
static SIZE_T room_after(HMODULE module, BYTE *target)
{
    BYTE *base = (BYTE *)module;
    IMAGE_NT_HEADERS *nt = (IMAGE_NT_HEADERS *)(base + ((IMAGE_DOS_HEADER *)base)->e_lfanew);
    IMAGE_DATA_DIRECTORY dir = nt->OptionalHeader.DataDirectory[IMAGE_DIRECTORY_ENTRY_EXPORT];
    IMAGE_EXPORT_DIRECTORY *exports = (IMAGE_EXPORT_DIRECTORY *)(base + dir.VirtualAddress);
    DWORD *functions = (DWORD *)(base + exports->AddressOfFunctions);
    DWORD own = (DWORD)(target - base), next = 0;
    DWORD i;
    for (i = 0; i < exports->NumberOfFunctions; i++) {
        DWORD rva = functions[i];
        if (rva > own && (!next || rva < next) && (rva < dir.VirtualAddress || rva >= dir.VirtualAddress + dir.Size))
            next = rva;
    }
    return next ? next - own : 0;
}

static int replace_iconic(void)
{
    HMODULE user32 = LoadLibraryW(L"user32.dll");
    BYTE *target = user32 ? (BYTE *)GetProcAddress(user32, "IsIconic") : NULL;
    SIZE_T room;
    DWORD old;

    if (!target) {
        focus_log("user32's IsIconic not found; Questlog's overlays stay over other programs");
        return 0;
    }
    room = room_after(user32, target);
    if (room < PATCH_BYTES) {
        focus_log("user32's IsIconic has %lu bytes before the next function, %d needed; not replaced, Questlog's "
                  "overlays stay over other programs", (unsigned long)room, PATCH_BYTES);
        return 0;
    }
    if (!VirtualProtect(target, PATCH_BYTES, PAGE_EXECUTE_READWRITE, &old)) {
        focus_log("could not make IsIconic writable (error %lu)", GetLastError());
        return 0;
    }
    target[0] = 0x48;                                      /* mov rax, fake_iconic */
    target[1] = 0xB8;
    *(void **)(target + 2) = (void *)fake_iconic;
    target[10] = 0xFF;                                     /* jmp rax */
    target[11] = 0xE0;
    VirtualProtect(target, PATCH_BYTES, old, &old);
    FlushInstructionCache(GetCurrentProcess(), target, PATCH_BYTES);
    return 1;
}

/* ---------------------------------------------------------------- the launcher's answers */

struct bridge {
    char host[64];
    unsigned short port;
    char token[129];
};

static int read_bridge(struct bridge *b)
{
    char value[512], *colon1, *colon2;
    DWORD n = GetEnvironmentVariableA("QUESTLOG_PROTON_BRIDGE", value, sizeof value);
    if (n == 0 || n >= sizeof value)
        return 0;
    colon1 = strchr(value, ':');
    colon2 = colon1 ? strchr(colon1 + 1, ':') : NULL;
    if (!colon2 || strchr(colon2 + 1, ':') || colon1 - value >= (int)sizeof b->host
        || strlen(colon2 + 1) >= sizeof b->token)
        return 0;
    *colon1 = *colon2 = 0;
    strcpy(b->host, value);
    b->port = (unsigned short)atoi(colon1 + 1);
    strcpy(b->token, colon2 + 1);
    return b->port != 0;
}

/* One connection: "QLPB2 <token> focus", then a line "in" or "out" now and on every change. */
static void follow(const struct bridge *b)
{
    struct sockaddr_in server;
    char hello[200], line[16];
    int len = 0;
    SOCKET s = socket(AF_INET, SOCK_STREAM, IPPROTO_TCP);
    if (s == INVALID_SOCKET)
        return;
    memset(&server, 0, sizeof server);
    server.sin_family = AF_INET;
    server.sin_port = htons(b->port);
    server.sin_addr.s_addr = inet_addr(b->host);
    snprintf(hello, sizeof hello, "QLPB2 %s focus\n", b->token);
    if (connect(s, (struct sockaddr *)&server, sizeof server) == 0
        && send(s, hello, (int)strlen(hello), 0) == (int)strlen(hello)) {
        char c;
        while (recv(s, &c, 1, 0) == 1) {
            if (c != '\n') {
                if (len < (int)sizeof line - 1)
                    line[len++] = c;
                continue;
            }
            line[len] = 0;
            len = 0;
            if (!strcmp(line, "out"))
                InterlockedExchange(&outside, 1);
            else if (!strcmp(line, "in"))
                InterlockedExchange(&outside, 0);
        }
    }
    closesocket(s);
    InterlockedExchange(&outside, 0);      /* without the launcher: the real answer */
}

static DWORD WINAPI follow_thread(void *arg)
{
    struct bridge b;
    WSADATA data;
    int told = 0;
    (void)arg;
    if (!read_bridge(&b) || WSAStartup(MAKEWORD(2, 2), &data) != 0) {
        focus_log("no capture bridge to follow; Questlog's overlays stay over other programs");
        return 0;
    }
    for (;;) {
        follow(&b);
        if (!told) {
            focus_log("the launcher's focus connection ended or could not be made; retrying every %d s",
                      RETRY_MS / 1000);
            told = 1;
        }
        Sleep(RETRY_MS);
    }
}

BOOL WINAPI DllMain(HINSTANCE instance, DWORD reason, void *reserved)
{
    (void)reserved;
    if (reason != DLL_PROCESS_ATTACH)
        return TRUE;
    DisableThreadLibraryCalls(instance);
    if (!load_real_version()) {
        focus_log("Wine's own version.dll could not be loaded; refusing to load in its place");
        return FALSE;                      /* without the real functions Questlog must not run on ours */
    }
    if (GetEnvironmentVariableA("QUESTLOG_PROTON_BRIDGE", NULL, 0) == 0 || strstr(GetCommandLineA(), "--type="))
        return TRUE;                       /* not A2Qlinux's Questlog, or not its main process */
    if (replace_iconic()) {
        HANDLE thread = CreateThread(NULL, 0, follow_thread, NULL, 0, NULL);
        if (thread)
            CloseHandle(thread);
        focus_log("the game counts as minimized for Questlog while a window that is not Wine's is active (%s)",
                  signature);
    }
    return TRUE;
}
