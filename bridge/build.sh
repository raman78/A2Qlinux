#!/bin/bash
# Build the Windows parts for x64 with clang and Wine's headers and import
# libraries; no MinGW toolchain is needed:
#   a2qlinux/bin/wpcap.dll        stand-in for Npcap's wpcap.dll, fed by the Linux side
#   a2qlinux/bin/questlog_ctl.exe acts on a running Questlog from inside its Wine session
#   bridge/tests/*.exe            test programs for the two above
#   tools/tcp_owner_probe.exe     diagnostic: does Wine report TCP connection owners
# Rebuild after a Wine update.
#
# Wine's files are looked for where the distributions put them (their package
# file lists, docs/ARCHITECTURE.md §14); WINE_INCLUDE and WINE_LIB override that.
# Anything missing is reported with the command that installs it.
set -euo pipefail
cd "$(dirname "$0")"

# Package names for building, per distribution family (/etc/os-release).
family=""
if [ -r /etc/os-release ]; then
    ids=" $(. /etc/os-release; echo "${ID:-} ${ID_LIKE:-}") "
    case "$ids" in
        *" arch "*) family=arch ;;
        *" ubuntu "*|*" debian "*) family=debian ;;
        *" fedora "*) family=fedora ;;
        *" suse "*|*" opensuse "*) family=suse ;;
    esac
fi
case "$family" in
    arch)   install="sudo pacman -S --needed clang lld wine" ;;
    debian) install="sudo apt install clang lld libwine-dev" ;;
    fedora) install="sudo dnf install clang lld wine-devel" ;;
    suse)   install="sudo zypper install clang lld wine-devel" ;;
    *)      install="install clang, lld and Wine's development files (headers and import libraries)" ;;
esac

missing=()
command -v clang >/dev/null || missing+=("clang")
command -v ld.lld >/dev/null || missing+=("lld (ld.lld)")

# Include root: the folder holding msvcrt/ and windows/ (Arch, Fedora, openSUSE:
# /usr/include/wine; Debian, Ubuntu: /usr/include/wine/wine).
W="${WINE_INCLUDE:-}"
if [ -z "$W" ]; then
    for candidate in /usr/include/wine /usr/include/wine/wine; do
        if [ -f "$candidate/windows/windows.h" ] && [ -d "$candidate/msvcrt" ]; then W="$candidate"; break; fi
    done
fi
[ -n "$W" ] && [ -f "$W/windows/windows.h" ] || missing+=("Wine's headers (windows/windows.h)")

# Import libraries for x86_64 Windows programs (Arch: /usr/lib/wine; openSUSE:
# /usr/lib64/wine; Debian, Ubuntu: /usr/lib/x86_64-linux-gnu/wine).
L="${WINE_LIB:-}"
if [ -z "$L" ]; then
    for candidate in /usr/lib/wine/x86_64-windows /usr/lib64/wine/x86_64-windows \
                     /usr/lib/x86_64-linux-gnu/wine/x86_64-windows; do
        if [ -f "$candidate/libkernel32.a" ]; then L="$candidate"; break; fi
    done
fi
[ -n "$L" ] && [ -f "$L/libkernel32.a" ] || missing+=("Wine's x86_64 import libraries (x86_64-windows/libkernel32.a)")

if [ ${#missing[@]} -gt 0 ]; then
    echo "bridge/build.sh: cannot build, missing: $(IFS=';'; echo "${missing[*]}" | sed 's/;/; /g')" >&2
    echo "  $install" >&2
    echo "  (Wine's files in other folders: set WINE_INCLUDE and WINE_LIB.)" >&2
    exit 1
fi
echo "Wine's headers: $W; import libraries: $L"

mkdir -p ../a2qlinux/bin
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
