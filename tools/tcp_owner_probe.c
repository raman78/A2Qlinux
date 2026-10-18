/* Probe: does Wine report the owning process of the game's TCP connections?
 *
 * Questlog's live capture path maps game connections to the game process with
 * GetExtendedTcpTable(TCP_TABLE_OWNER_PID_ALL). This prints every IPv4 TCP row
 * with remote or local port 13328, the owning PID, and that PID's executable
 * name from a Toolhelp snapshot. Read-only.
 */
#include <winsock2.h>
#include <windows.h>
#include <iphlpapi.h>
#include <tlhelp32.h>
#include <stdio.h>
#include <stdlib.h>

static void exe_name(DWORD pid, char *out, size_t size)
{
    PROCESSENTRY32 entry;
    HANDLE snap = CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0);
    snprintf(out, size, "?");
    if (snap == INVALID_HANDLE_VALUE) return;
    entry.dwSize = sizeof(entry);
    for (BOOL ok = Process32First(snap, &entry); ok; ok = Process32Next(snap, &entry))
        if (entry.th32ProcessID == pid) { snprintf(out, size, "%s", entry.szExeFile); break; }
    CloseHandle(snap);
}

static void ip(DWORD addr, char *out)
{
    unsigned char *b = (unsigned char *)&addr;
    sprintf(out, "%u.%u.%u.%u", b[0], b[1], b[2], b[3]);
}

int main(void)
{
    DWORD size = 0;
    DWORD rc = GetExtendedTcpTable(NULL, &size, FALSE, AF_INET, TCP_TABLE_OWNER_PID_ALL, 0);
    MIB_TCPTABLE_OWNER_PID *table = malloc(size + 4096);
    size += 4096;
    rc = GetExtendedTcpTable(table, &size, FALSE, AF_INET, TCP_TABLE_OWNER_PID_ALL, 0);
    if (rc != NO_ERROR) { printf("GetExtendedTcpTable failed: %lu\n", (unsigned long)rc); return 1; }
    printf("rows: %lu\n", (unsigned long)table->dwNumEntries);
    int shown = 0;
    for (DWORD i = 0; i < table->dwNumEntries; i++) {
        MIB_TCPROW_OWNER_PID *r = &table->table[i];
        unsigned lport = ntohs((u_short)r->dwLocalPort), rport = ntohs((u_short)r->dwRemotePort);
        if (lport != 13328 && rport != 13328) continue;
        char l[16], rem[16], name[MAX_PATH];
        ip(r->dwLocalAddr, l); ip(r->dwRemoteAddr, rem);
        exe_name(r->dwOwningPid, name, sizeof(name));
        printf("%s:%u -> %s:%u state=%lu pid=%lu exe=%s\n", l, lport, rem, rport,
               (unsigned long)r->dwState, (unsigned long)r->dwOwningPid, name);
        shown++;
    }
    printf("game-port rows: %d\n", shown);
    return 0;
}
