#!/bin/bash
# Build the Windows parts for x64 with clang and Wine's headers and import
# libraries; no MinGW toolchain is needed:
#   a2qlinux/bin/wpcap.dll        stand-in for Npcap's wpcap.dll, fed by the Linux side
#   a2qlinux/bin/questlog_ctl.exe acts on a running Questlog from inside its Wine session
#   bridge/tests/*.exe            test programs for the two above
#   tools/tcp_owner_probe.exe     diagnostic: does Wine report TCP connection owners
# Rebuild after a Wine update.
set -euo pipefail
cd "$(dirname "$0")"
mkdir -p ../a2qlinux/bin
W=/usr/include/wine
L=/usr/lib/wine/x86_64-windows
CF=(--target=x86_64-w64-windows-gnu -fuse-ld=lld -nostdinc -isystem "$W/msvcrt" -isystem "$W/windows"
    -isystem "$(clang -print-resource-dir)/include" -O2 -Wall -Wextra)
clang "${CF[@]}" -shared -o ../a2qlinux/bin/wpcap.dll wpcap_bridge.c -nostdlib -L"$L" -lucrtbase -lkernel32 -luser32 -lws2_32 \
    -Wl,--entry=DllMain
clang "${CF[@]}" -o ../a2qlinux/bin/questlog_ctl.exe questlog_ctl.c -nostdlib -L"$L" -lucrtbase -lkernel32 -luser32 \
    -lshell32 -Wl,--entry=start
clang "${CF[@]}" -o tests/bridge_client_test.exe tests/bridge_client_test.c -nostdlib -L"$L" -lucrtbase -lkernel32 \
    -Wl,--entry=main
clang "${CF[@]}" -o tests/zorder_guard_test.exe tests/zorder_guard_test.c -nostdlib -L"$L" -lucrtbase -lkernel32 \
    -luser32 -lshell32 -Wl,--entry=start
clang "${CF[@]}" -o ../tools/tcp_owner_probe.exe ../tools/tcp_owner_probe.c -nostdlib -L"$L" -lucrtbase \
    -lkernel32 -liphlpapi -lws2_32 -Wl,--entry=main
echo "built: a2qlinux/bin/wpcap.dll, a2qlinux/bin/questlog_ctl.exe, bridge/tests/*.exe, tools/tcp_owner_probe.exe"
