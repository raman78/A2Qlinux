#!/bin/bash
# Install A2Qlinux from this copy of the repository, for changing A2Qlinux
# itself (docs/INSTALL.md, "From the source code instead"). In order:
#   1. bridge/build.sh   builds the Windows parts into a2qlinux/bin/ (the
#                        PyPI package ships them built; a checkout does not)
#   2. pipx install --editable .
#                        installs this folder, so edits take effect at the
#                        next start without reinstalling; an installation
#                        that is already there is replaced first
#   3. pipx ensurepath   puts pipx's command folder on the command path
#   4. a2qlinux-setup    the same checks and setup as after a PyPI install;
#                        options given here are passed on to it
# Nothing runs with sudo; what needs it is printed for you to run.
set -euo pipefail
cd "$(dirname "$0")"

command -v pipx >/dev/null || {
    echo "install-from-source.sh: pipx is missing; install it first (docs/INSTALL.md, 'Installing the packages')." >&2
    exit 1
}

echo "== 1/4 Building the Windows parts"
bash bridge/build.sh

echo "== 2/4 Installing this copy with pipx"
if pipx list --short 2>/dev/null | grep -q '^a2qlinux '; then
    echo "Replacing the A2Qlinux installation that is already there."
    pipx uninstall a2qlinux
fi
pipx install --editable .

echo "== 3/4 Putting pipx's commands on the command path"
pipx ensurepath

echo "== 4/4 Setting up"
# This shell started before ensurepath; give the setup the path new terminals will have,
# so the menu entry it writes points at pipx's stable command folder.
export PATH="${PIPX_BIN_DIR:-$HOME/.local/bin}:$PATH"
a2qlinux-setup "$@"
