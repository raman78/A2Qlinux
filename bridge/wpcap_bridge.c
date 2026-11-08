/* wpcap.dll stand-in for Questlog Desktop running under Proton.
 *
 * Questlog captures game traffic by calling a handful of libpcap functions in
 * C:\Windows\System32\Npcap\wpcap.dll. Npcap is a Windows driver and cannot
 * work under Wine, so this DLL takes its place: it hands Questlog the packets
 * that A2Qlinux's launcher captures with dumpcap on the Linux side, over a
 * localhost TCP connection.
 *
 * Only the calls Questlog makes are implemented. Their behaviour follows what
 * Questlog's capture loop expects:
 *   pcap_findalldevs   one device per interface the launcher captures on, each
 *                      with its IPv4 address, asked from the bridge on every
 *                      call (Questlog picks the device whose address its game
 *                      connection uses, and lists again for each new one)
 *   pcap_open_live     connect to the bridge, authenticate with its token and
 *                      ask for that interface's packets
 *   pcap_next_ex       1 = packet, 0 = none waiting (non-blocking), -1 = error
 *   pcap_compile/setfilter  accepted and ignored: dumpcap filters already
 *
 * Configuration comes from the environment, set by the launcher:
 *   QUESTLOG_PROTON_BRIDGE=<host>:<port>:<token>
 * The request lines and replies are described in a2qlinux/pcap_bridge.py.
 * Without it every entry point fails with a message saying so, which Questlog
 * shows in its interface instead of silently counting nothing.
 *
 * The DLL also runs the window-order guard (see its section below), because it
 * is the one piece of our code that lives inside Questlog's Wine session.
 */

#include <winsock2.h>
#include <windows.h>
#include <stdlib.h>
#include <string.h>
#include <stdio.h>
#include <stdarg.h>

#define PCAP_ERRBUF_SIZE 256
#define MAX_RECORD (16 + 262144)
#define BRIDGE_SIGNATURE "questlog-proton bridge"
/* Device names are this prefix + the Linux interface name (at most 15 bytes). */
#define DEVICE_PREFIX "\\Device\\NPF_A2Qlinux_"
#define IFNAME_MAX 16
#define MAX_DEVICES 64

/* Layouts as Questlog declares them (and as Npcap defines them on Win64). */
struct pcap_addr {
    struct pcap_addr *next;
    struct sockaddr *addr, *netmask, *broadaddr, *dstaddr;
};

typedef struct pcap_if {
    struct pcap_if *next;
    char *name;
    char *description;
    struct pcap_addr *addresses;
    unsigned int flags;
} pcap_if_t;

struct pcap_pkthdr {            /* struct timeval has 32-bit longs on Windows */
    int seconds;
    int microseconds;
    unsigned int caplen;
    unsigned int len;
};

struct bpf_program {
    unsigned int bf_len;
    void *bf_insns;
};

typedef struct pcap {
    SOCKET sock;
    int linktype;
    unsigned char *buf;
    size_t cap, start, end;
    struct pcap_pkthdr hdr;
    char err[PCAP_ERRBUF_SIZE];
} pcap_t;

struct config {
    char host[64];
    unsigned short port;
    char token[129];
};

static void set_error(char *dst, const char *fmt, const char *detail)
{
    snprintf(dst, PCAP_ERRBUF_SIZE, fmt, detail ? detail : "");
}

static int read_config(struct config *c, char *errbuf)
{
    char value[512], *parts[3], *p;
    DWORD n = GetEnvironmentVariableA("QUESTLOG_PROTON_BRIDGE", value, sizeof(value));
    int i;
    if (n == 0 || n >= sizeof(value)) {
        set_error(errbuf, "No capture bridge: start Questlog with A2Qlinux%s", NULL);
        return -1;
    }
    p = value;
    for (i = 0; i < 3; i++) {
        parts[i] = p;
        p = strchr(p, ':');
        if (i < 2) {
            if (!p) {
                set_error(errbuf, "QUESTLOG_PROTON_BRIDGE is malformed: %s", value);
                return -1;
            }
            *p++ = 0;
        } else if (p) {
            set_error(errbuf, "QUESTLOG_PROTON_BRIDGE is from another A2Qlinux version: restart Questlog "
                              "through A2Qlinux%s", NULL);
            return -1;
        }
    }
    if (strlen(parts[0]) >= sizeof(c->host) || strlen(parts[2]) >= sizeof(c->token)
        || atoi(parts[1]) <= 0 || atoi(parts[1]) > 65535) {
        set_error(errbuf, "QUESTLOG_PROTON_BRIDGE has a bad field%s", NULL);
        return -1;
    }
    strcpy(c->host, parts[0]);
    c->port = (unsigned short)atoi(parts[1]);
    strcpy(c->token, parts[2]);
    return 0;
}

static int winsock_ready(char *errbuf)
{
    static int started;
    WSADATA data;
    if (started)
        return 0;
    if (WSAStartup(MAKEWORD(2, 2), &data) != 0) {
        set_error(errbuf, "WSAStartup failed%s", NULL);
        return -1;
    }
    started = 1;
    return 0;
}

static int recv_exact(SOCKET s, unsigned char *dst, int len)
{
    int got = 0;
    while (got < len) {
        int n = recv(s, (char *)dst + got, len - got, 0);
        if (n <= 0)
            return -1;
        got += n;
    }
    return 0;
}

/* One reply line, without its newline; -1 when the connection ends first or
 * the line does not fit. Byte by byte: replies are a few short lines, and the
 * packet stream that may follow must stay in the socket. */
static int recv_line(SOCKET s, char *line, int size)
{
    int got = 0;
    for (;;) {
        char ch;
        if (recv(s, &ch, 1, 0) != 1 || got >= size - 1)
            return -1;
        if (ch == '\n')
            break;
        line[got++] = ch;
    }
    line[got] = 0;
    return 0;
}

/* Connect to the bridge and send one request ("list", "open <interface>"). */
static SOCKET bridge_request(const struct config *c, const char *request, char *errbuf)
{
    struct sockaddr_in server;
    char hello[200];
    SOCKET s;

    if (winsock_ready(errbuf) != 0)
        return INVALID_SOCKET;
    s = socket(AF_INET, SOCK_STREAM, IPPROTO_TCP);
    if (s == INVALID_SOCKET) {
        set_error(errbuf, "socket() failed%s", NULL);
        return INVALID_SOCKET;
    }
    memset(&server, 0, sizeof(server));
    server.sin_family = AF_INET;
    server.sin_port = htons(c->port);
    server.sin_addr.s_addr = inet_addr(c->host);
    if (connect(s, (struct sockaddr *)&server, sizeof(server)) != 0) {
        closesocket(s);
        set_error(errbuf, "Capture bridge not reachable (is A2Qlinux running?)%s", NULL);
        return INVALID_SOCKET;
    }
    snprintf(hello, sizeof(hello), "QLPB2 %s %s\n", c->token, request);
    if (send(s, hello, (int)strlen(hello), 0) != (int)strlen(hello)) {
        closesocket(s);
        set_error(errbuf, "Capture bridge closed the connection at start - see the A2Qlinux window%s", NULL);
        return INVALID_SOCKET;
    }
    return s;
}

/* --- Window-order guard ---
 *
 * Questlog shares a Wine session with the game. While the game is in the
 * foreground it confines the cursor (ClipCursor); Wine does that by grabbing
 * the pointer with one session-wide clip window, so clicks reach wineserver
 * with no target window and the server hands them to whichever window is on
 * top at that point in its *own* z-order. That order is not updated when the
 * window manager raises the game, so Questlog's main window - last active -
 * stays above the game there and takes the clicks meant for the game.
 *
 * The guard keeps Wine's order in line with the screen: whenever a window of
 * another program is in the foreground, every ordinary Questlog window that
 * Wine has above it is moved directly below it, without activating it.
 * Overlay windows are left alone: they are topmost or non-activatable
 * (WS_EX_NOACTIVATE), and Questlog orders them itself. Every move is logged
 * to stderr, which the launcher writes to questlog.log. */

#define GUARD_INTERVAL_MS 50

static WCHAR own_image[MAX_PATH];

static void guard_log(const char *fmt, ...)
{
    char line[512];
    DWORD written;
    va_list args;
    int n;

    va_start(args, fmt);
    n = vsnprintf(line, sizeof(line) - 1, fmt, args);
    va_end(args);
    if (n < 0)
        return;
    if (n > (int)sizeof(line) - 2)
        n = (int)sizeof(line) - 2;
    line[n++] = '\n';
    WriteFile(GetStdHandle(STD_ERROR_HANDLE), line, (DWORD)n, &written, NULL);
}

/* Full image path of the process owning a window; 0 when it cannot be read. */
static int window_image(HWND w, WCHAR *image)
{
    DWORD pid = 0, size = MAX_PATH;
    HANDLE process;
    int ok;

    GetWindowThreadProcessId(w, &pid);
    if (!pid || !(process = OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, FALSE, pid)))
        return 0;
    ok = QueryFullProcessImageNameW(process, 0, image, &size);
    CloseHandle(process);
    return ok;
}

/* Questlog's windows live in its browser process, not in the utility process
 * that loads this DLL, so they are recognised by program, not by process. */
static int is_questlog_window(HWND w)
{
    WCHAR image[MAX_PATH];
    return window_image(w, image) && lstrcmpiW(image, own_image) == 0;
}

static int is_ordinary_window(HWND w)
{
    LONG ex = GetWindowLongW(w, GWL_EXSTYLE);
    return IsWindowVisible(w) && !IsIconic(w) && !(ex & (WS_EX_TOPMOST | WS_EX_NOACTIVATE));
}

static void program_name(const WCHAR *image, char *name, int size)
{
    const WCHAR *base = wcsrchr(image, L'\\');
    if (!WideCharToMultiByte(CP_UTF8, 0, base ? base + 1 : image, -1, name, size, NULL, NULL))
        snprintf(name, size, "?");
}

static void guard_once(void)
{
    static HWND failed_window;
    static DWORD failed_error;
    HWND foreground = GetForegroundWindow(), w, above;
    WCHAR image[MAX_PATH];
    char name[MAX_PATH];

    if (!foreground || foreground == GetDesktopWindow() || !window_image(foreground, image)
        || lstrcmpiW(image, own_image) == 0)
        return;
    for (w = GetWindow(foreground, GW_HWNDPREV); w; w = above) {
        above = GetWindow(w, GW_HWNDPREV);
        if (!is_ordinary_window(w) || !is_questlog_window(w))
            continue;
        program_name(image, name, sizeof(name));
        if (SetWindowPos(w, foreground, 0, 0, 0, 0,
                         SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE | SWP_NOOWNERZORDER)) {
            guard_log("[a2qlinux] Questlog window %p was above the foreground window %p (%s) "
                      "in Wine's window order, so clicks there would reach Questlog; moved it below.",
                      (void *)w, (void *)foreground, name);
            failed_window = NULL;
        } else if (w != failed_window || GetLastError() != failed_error) {
            failed_window = w;
            failed_error = GetLastError();
            guard_log("[a2qlinux] Questlog window %p is above the foreground window %p (%s) "
                      "in Wine's window order and could not be moved below it (error %lu); "
                      "clicks there will reach Questlog.",
                      (void *)w, (void *)foreground, name, failed_error);
        }
    }
}

static DWORD WINAPI guard_thread(void *arg)
{
    (void)arg;
    for (;;) {
        Sleep(GUARD_INTERVAL_MS);
        guard_once();
    }
    return 0;
}

/* Started on Questlog's first call into the DLL. The module is pinned because
 * the thread runs its code for the rest of the process's life. */
static void start_window_guard(void)
{
    static LONG started;
    DWORD size = MAX_PATH;
    HMODULE self;
    HANDLE thread;

    if (InterlockedExchange(&started, 1))
        return;
    if (!QueryFullProcessImageNameW(GetCurrentProcess(), 0, own_image, &size)) {
        guard_log("[a2qlinux] Window-order guard not started: cannot read Questlog's program path "
                  "(error %lu); clicks in the game may reach Questlog's window.", GetLastError());
        return;
    }
    if (!GetModuleHandleExW(GET_MODULE_HANDLE_EX_FLAG_FROM_ADDRESS | GET_MODULE_HANDLE_EX_FLAG_PIN,
                            (LPCWSTR)start_window_guard, &self)
        || !(thread = CreateThread(NULL, 0, guard_thread, NULL, 0, NULL))) {
        guard_log("[a2qlinux] Window-order guard not started (error %lu); "
                  "clicks in the game may reach Questlog's window.", GetLastError());
        return;
    }
    CloseHandle(thread);
}

__declspec(dllexport) const char *pcap_lib_version(void)
{
    return BRIDGE_SIGNATURE " (wpcap.dll stand-in for Questlog under Proton)";
}

__declspec(dllexport) void pcap_freealldevs(pcap_if_t *alldevs);

static pcap_if_t *new_device(const char *ifname, unsigned long ip)
{
    pcap_if_t *dev = calloc(1, sizeof(*dev));
    struct pcap_addr *addr = calloc(1, sizeof(*addr));
    struct sockaddr_in *sin = calloc(1, sizeof(*sin));
    char name[sizeof(DEVICE_PREFIX) + IFNAME_MAX], description[IFNAME_MAX + 40];

    if (!dev || !addr || !sin) {
        free(dev); free(addr); free(sin);
        return NULL;
    }
    snprintf(name, sizeof(name), "%s%s", DEVICE_PREFIX, ifname);
    snprintf(description, sizeof(description), "%s through the A2Qlinux capture bridge", ifname);
    sin->sin_family = AF_INET;
    sin->sin_addr.s_addr = ip;
    addr->addr = (struct sockaddr *)sin;
    dev->addresses = addr;
    dev->name = _strdup(name);
    dev->description = _strdup(description);
    if (!dev->name || !dev->description) {
        free(dev->name); free(dev->description); free(dev); free(addr); free(sin);
        return NULL;
    }
    return dev;
}

__declspec(dllexport) int pcap_findalldevs(pcap_if_t **alldevs, char *errbuf)
{
    struct config c;
    pcap_if_t *first = NULL, **tail = &first;
    char line[128], ifname[IFNAME_MAX], ip[16];
    SOCKET s;
    int count = 0;

    *alldevs = NULL;
    start_window_guard();
    if (read_config(&c, errbuf) != 0)
        return -1;
    s = bridge_request(&c, "list", errbuf);
    if (s == INVALID_SOCKET)
        return -1;
    for (;;) {
        unsigned long address;
        if (recv_line(s, line, sizeof(line)) != 0) {
            set_error(errbuf, "Capture bridge closed the connection while listing interfaces - "
                              "see the A2Qlinux window%s", NULL);
            break;
        }
        if (!line[0]) {
            closesocket(s);
            *alldevs = first;
            return 0;
        }
        if (sscanf(line, "%15s %15s", ifname, ip) != 2 || (address = inet_addr(ip)) == INADDR_NONE) {
            set_error(errbuf, "Capture bridge listed an unreadable interface: %s", line);
            break;
        }
        if (++count > MAX_DEVICES) {
            set_error(errbuf, "Capture bridge listed too many interfaces%s", NULL);
            break;
        }
        if (!(*tail = new_device(ifname, address))) {
            set_error(errbuf, "Out of memory%s", NULL);
            break;
        }
        tail = &(*tail)->next;
    }
    closesocket(s);
    pcap_freealldevs(first);
    return -1;
}

__declspec(dllexport) void pcap_freealldevs(pcap_if_t *alldevs)
{
    while (alldevs) {
        pcap_if_t *next = alldevs->next;
        struct pcap_addr *a = alldevs->addresses;
        while (a) {
            struct pcap_addr *an = a->next;
            free(a->addr);
            free(a);
            a = an;
        }
        free(alldevs->name);
        free(alldevs->description);
        free(alldevs);
        alldevs = next;
    }
}

__declspec(dllexport) pcap_t *pcap_open_live(const char *device, int snaplen, int promisc, int to_ms, char *errbuf)
{
    struct config c;
    unsigned char header[24];
    char request[sizeof("open ") + IFNAME_MAX], reply[PCAP_ERRBUF_SIZE];
    const char *ifname;
    unsigned int magic;
    pcap_t *p;
    SOCKET s;

    (void)snaplen; (void)promisc; (void)to_ms;
    start_window_guard();
    if (read_config(&c, errbuf) != 0)
        return NULL;
    if (!device || strncmp(device, DEVICE_PREFIX, strlen(DEVICE_PREFIX)) != 0
        || !*(ifname = device + strlen(DEVICE_PREFIX)) || strlen(ifname) >= IFNAME_MAX || strchr(ifname, ' ')) {
        set_error(errbuf, "Not a device of the A2Qlinux capture bridge: %s", device ? device : "(none)");
        return NULL;
    }
    snprintf(request, sizeof(request), "open %s", ifname);
    s = bridge_request(&c, request, errbuf);
    if (s == INVALID_SOCKET)
        return NULL;
    if (recv_line(s, reply, sizeof(reply)) != 0) {
        closesocket(s);
        set_error(errbuf, "Capture bridge closed the connection at start - see the A2Qlinux window%s", NULL);
        return NULL;
    }
    if (strcmp(reply, "OK") != 0) {
        closesocket(s);
        set_error(errbuf, "%s", strncmp(reply, "ERR ", 4) == 0 ? reply + 4 : reply);
        return NULL;
    }
    if (recv_exact(s, header, 24) != 0) {
        closesocket(s);
        set_error(errbuf, "Capture bridge closed the connection at start - see the A2Qlinux window%s", NULL);
        return NULL;
    }
    memcpy(&magic, header, 4);
    if (magic != 0xA1B2C3D4u) {
        closesocket(s);
        set_error(errbuf, "Capture bridge sent an unexpected stream format%s", NULL);
        return NULL;
    }
    p = calloc(1, sizeof(*p));
    if (!p) {
        closesocket(s);
        set_error(errbuf, "Out of memory%s", NULL);
        return NULL;
    }
    p->sock = s;
    memcpy(&p->linktype, header + 20, 4);
    p->cap = 1 << 20;
    p->buf = malloc(p->cap);
    if (!p->buf) {
        closesocket(s);
        free(p);
        set_error(errbuf, "Out of memory%s", NULL);
        return NULL;
    }
    return p;
}

__declspec(dllexport) int pcap_setnonblock(pcap_t *p, int nonblock, char *errbuf)
{
    u_long mode = nonblock ? 1 : 0;
    if (ioctlsocket(p->sock, FIONBIO, &mode) != 0) {
        set_error(errbuf, "ioctlsocket(FIONBIO) failed%s", NULL);
        return -1;
    }
    return 0;
}

__declspec(dllexport) int pcap_datalink(pcap_t *p)
{
    return p->linktype;
}

__declspec(dllexport) int pcap_compile(pcap_t *p, struct bpf_program *program, const char *filter,
                                       int optimize, unsigned int netmask)
{
    (void)p; (void)filter; (void)optimize; (void)netmask;
    program->bf_len = 0;
    program->bf_insns = NULL;
    return 0;
}

__declspec(dllexport) int pcap_setfilter(pcap_t *p, struct bpf_program *program)
{
    (void)p; (void)program;
    return 0;
}

__declspec(dllexport) void pcap_freecode(struct bpf_program *program)
{
    (void)program;
}

__declspec(dllexport) int pcap_next_ex(pcap_t *p, struct pcap_pkthdr **header, const unsigned char **data)
{
    for (;;) {
        size_t avail = p->end - p->start;
        size_t need = 16;
        int n;

        if (avail >= 16) {
            struct pcap_pkthdr h;
            memcpy(&h, p->buf + p->start, 16);
            if (h.caplen > MAX_RECORD - 16) {
                snprintf(p->err, sizeof(p->err), "Capture bridge sent an oversized packet (%u bytes)", h.caplen);
                return -1;
            }
            need = 16 + h.caplen;
            if (avail >= need) {
                p->hdr = h;
                *header = &p->hdr;
                *data = p->buf + p->start + 16;
                p->start += need;
                return 1;
            }
        }
        /* Not a whole record buffered: make room, then read what has arrived.
         * The previous record's bytes may move; Questlog has copied them. */
        if (p->start > 0) {
            memmove(p->buf, p->buf + p->start, avail);
            p->start = 0;
            p->end = avail;
        }
        if (p->cap - p->end < 65536 || p->cap < need) {
            size_t cap = p->cap * 2;
            unsigned char *grown;
            while (cap < need)
                cap *= 2;
            grown = realloc(p->buf, cap);
            if (!grown) {
                snprintf(p->err, sizeof(p->err), "Out of memory");
                return -1;
            }
            p->buf = grown;
            p->cap = cap;
        }
        n = recv(p->sock, (char *)p->buf + p->end, (int)(p->cap - p->end), 0);
        if (n > 0) {
            p->end += (size_t)n;
            continue;
        }
        if (n == 0) {
            snprintf(p->err, sizeof(p->err), "Capture bridge closed the connection (A2Qlinux stopped?)");
            return -1;
        }
        if (WSAGetLastError() == WSAEWOULDBLOCK)
            return 0;
        snprintf(p->err, sizeof(p->err), "Capture bridge connection failed (error %d)", WSAGetLastError());
        return -1;
    }
}

__declspec(dllexport) char *pcap_geterr(pcap_t *p)
{
    return p->err;
}

__declspec(dllexport) void pcap_close(pcap_t *p)
{
    if (!p)
        return;
    closesocket(p->sock);
    free(p->buf);
    free(p);
}

BOOL WINAPI DllMain(HINSTANCE instance, DWORD reason, LPVOID reserved)
{
    (void)instance; (void)reason; (void)reserved;
    return TRUE;
}
