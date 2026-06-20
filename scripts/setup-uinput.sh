#!/usr/bin/env bash

# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU Affero General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
# 
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU Affero General Public License for more details.
# 
# You should have received a copy of the GNU Affero General Public License
# along with this program.  If not, see <https://www.gnu.org/licenses/>.

# Enable inline typing for TuxVox experimental mode.
#
# TuxVox types transcribed text by injecting key events through
# /dev/uinput. By default that device is owned by root and not writable by
# normal users. This script installs a udev rule granting the "input" group
# read/write access, ensures the uinput kernel module is loaded at boot, and
# applies the permissions immediately for the current session.
#
# Run once:  sudo bash scripts/setup-uinput.sh
set -euo pipefail

if [[ $EUID -ne 0 ]]; then
    echo "This script must be run as root. Try:" >&2
    echo "  sudo bash $0" >&2
    exit 1
fi

TARGET_USER="${SUDO_USER:-$USER}"

echo "==> Ensuring the 'uinput' kernel module is loaded..."
modprobe uinput || true
echo "uinput" > /etc/modules-load.d/uinput.conf

echo "==> Adding '$TARGET_USER' to the 'input' group..."
if ! id -nG "$TARGET_USER" | tr ' ' '\n' | grep -qx input; then
    usermod -aG input "$TARGET_USER"
    echo "    Added. You must reboot your computer for group membership to apply."
else
    echo "    Already a member of 'input'."
fi

echo "==> Installing udev rule for /dev/uinput..."
RULE_FILE="/etc/udev/rules.d/99-tuxvox-uinput.rules"
cat > "$RULE_FILE" <<'EOF'
KERNEL=="uinput", GROUP="input", MODE="0660", OPTIONS+="static_node=uinput"
EOF
echo "    Wrote $RULE_FILE"

echo "==> Reloading udev rules..."
udevadm control --reload-rules
udevadm trigger /dev/uinput || udevadm trigger || true

echo "==> Applying permissions to /dev/uinput for the current session..."
if [[ -e /dev/uinput ]]; then
    chgrp input /dev/uinput || true
    chmod 660 /dev/uinput || true
    ls -l /dev/uinput
else
    echo "    /dev/uinput does not exist yet; it will appear once uinput is loaded."
fi

echo
echo "Done. If '$TARGET_USER' was just added to the 'input' group, reboot your"
echo "computer so the change takes effect, then restart TuxVox."