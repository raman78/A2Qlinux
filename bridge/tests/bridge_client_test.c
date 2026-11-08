/* Test client for wpcap.dll: calls it the way Questlog's capture loop does
 * (findalldevs, then open_live on the device whose address is the one given
 * as the first argument - Questlog uses its game connection's local address -
 * or on the first device without one; setnonblock, datalink,
 * compile/setfilter, then next_ex until it returns 0, every 25 ms) and writes
 * a report to C:\bridge_client_test.txt: every listed device, packets
 * received and, per packet, receive time minus the capture timestamp in its
 * header (the end-to-end delay). */
#include <windows.h>
#include <stdio.h>
#include <string.h>

struct pcap_addr { struct pcap_addr *next; struct sockaddr *addr, *netmask, *broadaddr, *dstaddr; };
typedef struct pcap_if { struct pcap_if *next; char *name; char *description; struct pcap_addr *addresses; unsigned flags; } pcap_if_t;
struct pcap_pkthdr { int seconds; int microseconds; unsigned caplen; unsigned len; };
struct bpf_program { unsigned bf_len; void *bf_insns; };

typedef int (*findalldevs_t)(pcap_if_t **, char *);
typedef void *(*open_live_t)(const char *, int, int, int, char *);
typedef int (*setnonblock_t)(void *, int, char *);
typedef int (*datalink_t)(void *);
typedef int (*compile_t)(void *, struct bpf_program *, const char *, int, unsigned);
typedef int (*setfilter_t)(void *, struct bpf_program *);
typedef int (*next_ex_t)(void *, struct pcap_pkthdr **, const unsigned char **);
typedef char *(*geterr_t)(void *);
typedef const char *(*version_t)(void);

static long long now_ms(void)
{
    FILETIME ft;
    GetSystemTimePreciseAsFileTime(&ft);
    return (((long long)ft.dwHighDateTime << 32 | ft.dwLowDateTime) - 116444736000000000LL) / 10000;
}

int main(void)
{
    char path[MAX_PATH], err[256] = "";
    FILE *out = fopen("C:\\bridge_client_test.txt", "w");
    GetEnvironmentVariableA("SystemRoot", path, MAX_PATH);
    strcat(path, "\\System32\\Npcap\\wpcap.dll");
    HMODULE m = LoadLibraryA(path);
    if (!m) { fprintf(out, "load failed %lu\n", GetLastError()); fclose(out); return 1; }
    fprintf(out, "library: %s\n", ((version_t)GetProcAddress(m, "pcap_lib_version"))());
    pcap_if_t *devs;
    if (((findalldevs_t)GetProcAddress(m, "pcap_findalldevs"))(&devs, err) != 0) {
        fprintf(out, "findalldevs error: %s\n", err); fclose(out); return 1;
    }
    /* Built with main as the entry point and no C runtime start-up code
     * (build.sh), so there is no argv: the address is the command line's last word. */
    const char *want = strrchr(GetCommandLineA(), ' ');
    want = want && strchr(want, '.') ? want + 1 : NULL;
    pcap_if_t *chosen = NULL;
    for (pcap_if_t *d = devs; d; d = d->next) {
        unsigned char *a = (unsigned char *)d->addresses->addr;
        char ip[16];
        snprintf(ip, sizeof(ip), "%u.%u.%u.%u", a[4], a[5], a[6], a[7]);
        fprintf(out, "device: %s (%s) family=%u ip=%s\n", d->name, d->description, *(unsigned short *)a, ip);
        if (!chosen && (!want || strcmp(ip, want) == 0))
            chosen = d;
    }
    if (!chosen) { fprintf(out, "no device with address %s\n", want ? want : "(any)"); fclose(out); return 1; }
    fprintf(out, "opening: %s\n", chosen->name);
    void *p = ((open_live_t)GetProcAddress(m, "pcap_open_live"))(chosen->name, 65535, 0, 1, err);
    if (!p) { fprintf(out, "open_live error: %s\n", err); fclose(out); return 1; }
    ((setnonblock_t)GetProcAddress(m, "pcap_setnonblock"))(p, 1, err);
    struct bpf_program prog;
    ((compile_t)GetProcAddress(m, "pcap_compile"))(p, &prog, "tcp and (port 1)", 1, 0xffffffff);
    ((setfilter_t)GetProcAddress(m, "pcap_setfilter"))(p, &prog);
    fprintf(out, "datalink: %d\n", ((datalink_t)GetProcAddress(m, "pcap_datalink"))(p));
    next_ex_t next = (next_ex_t)GetProcAddress(m, "pcap_next_ex");
    long long start = now_ms(), worst = 0, total = 0, count = 0, bytes = 0;
    int rc = 0;
    while (now_ms() - start < 20000) {
        struct pcap_pkthdr *h; const unsigned char *d;
        while ((rc = next(p, &h, &d)) == 1) {
            long long delay = now_ms() - ((long long)h->seconds * 1000 + h->microseconds / 1000);
            if (delay > worst) worst = delay;
            total += delay; count++; bytes += h->caplen;
        }
        if (rc < 0) { fprintf(out, "next_ex error: %s\n", ((geterr_t)GetProcAddress(m, "pcap_geterr"))(p)); break; }
        Sleep(25);
    }
    fprintf(out, "packets: %lld bytes: %lld avg delay ms: %lld worst delay ms: %lld\n",
            count, bytes, count ? total / count : 0, worst);
    fclose(out);
    return 0;
}
