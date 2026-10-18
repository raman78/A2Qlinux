#!/bin/bash
# Steam launch-option wrapper for AION 2: start Questlog's capture bridge, then the game.
#
# Steam > AION 2 > Properties > General > Launch Options:
#     /path/to/A2Qlinux/steam_launch.sh %command%
# To close Questlog together with the game, put the option before %command%:
#     /path/to/A2Qlinux/steam_launch.sh --close-with-game %command%
# Questlog unpacked somewhere other than ~/Games/Questlog: put QUESTLOG_DIR=<dir> in front.
#
# The bridge is started through the user's systemd manager, not as a child of
# this script: it then runs with the desktop session's environment instead of
# Steam's (overlay preload, container variables), and Steam does not count it
# as part of the game. Whatever happens to it, the game is started.

here="$(dirname "$(readlink -f "$0")")"
# Decided before anything is started here: was a launcher (and so possibly a
# Questlog) already running when Play was pressed?
state="${QUESTLOG_DIR:-$HOME/Games/Questlog}/proton-stream"
lock="$state/.lock"
launcher_was_running=
if [ -e "$lock" ] && ! flock -n "$lock" true 2>/dev/null; then
    launcher_was_running=yes
fi

# Questlog starts once the game process is up (--wait-for-game), so the two
# never bring up the prefix's Wine at the same moment.
options=(--wait-for-game)
while [ "${1:-}" = "--close-with-game" ]; do
    options+=("$1")
    shift
done
if ! systemd-run --user --quiet --collect --unit="questlog-aion2-$$" \
        /usr/bin/python3 "$here/questlog_desktop.py" "${options[@]}" >/dev/null 2>&1; then
    notify-send --app-name="Questlog (AION 2)" "Questlog (AION 2)" \
        "Could not start Questlog from the Steam launch option; start it from its icon." 2>/dev/null
fi
# Questlog may already run in the game's prefix (started from its icon, e.g. to
# look through saved fights). Proton's waitforexitandrun would then wait for
# the prefix to go idle - i.e. until Questlog is closed. While the launcher is
# running, Proton is asked to "run" instead: the game joins the Wine session
# Questlog runs in and Questlog sees it at once. Otherwise nothing changes.
# Only Proton's own verb is switched; Steam's runtime keeps --verb=waitforexitandrun.
if [ -n "$launcher_was_running" ]; then
    args=("$@")
    for i in "${!args[@]}"; do
        if [ "$i" -gt 0 ] && [ "${args[$i]}" = "waitforexitandrun" ] && [[ "${args[$((i - 1))]}" == */proton ]]; then
            args[$i]=run
            echo "$(date '+%F %T') Questlog launcher running: Proton verb waitforexitandrun -> run" \
                >> "$state/steam_launch.log"
            break
        fi
    done
    set -- "${args[@]}"
fi
exec "$@"
