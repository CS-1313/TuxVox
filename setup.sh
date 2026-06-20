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

# ──────────────────────────────────────────────────────────────────
# TuxVox — Setup Script
#
# Creates a Python virtual environment with all dependencies and
# installs a desktop launcher so you can run TuxVox from your
# application menu.
#
# Usage:
#   cd ~/Documents/TuxVox
#   ./setup.sh
#
# After setup, run with:
#   ./run.sh
# ──────────────────────────────────────────────────────────────────
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="$SCRIPT_DIR/.venv"

echo "🎙  TuxVox Setup"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

# ── Step 1: System dependencies ──────────────────────────────────
echo "📦 Step 1/5: Checking system dependencies..."

MISSING_PKGS=()

# Detect OS
if [ -f /etc/os-release ]; then
    . /etc/os-release
    OS=$ID
    OS_LIKE=${ID_LIKE:-""}
else
    OS=$(uname -s)
    OS_LIKE=""
fi

if [[ "$OS" == "ubuntu" || "$OS" == "debian" || "$OS" == "kali" || "$OS_LIKE" == *"debian"* || "$OS_LIKE" == *"ubuntu"* ]]; then
    check_pkg() {
        if ! dpkg -s "$1" &>/dev/null; then
            MISSING_PKGS+=("$1")
        fi
    }
    check_pkg "libportaudio2"
    check_pkg "ffmpeg"
    check_pkg "libsndfile1"
    check_pkg "python3-gi"
    check_pkg "gir1.2-gtk-4.0"
    check_pkg "gir1.2-adw-1"

    if [ ${#MISSING_PKGS[@]} -gt 0 ]; then
        echo "   Installing missing system packages: ${MISSING_PKGS[*]}"
        echo "   (This may ask for your password)"
        echo ""
        sudo apt-get update
        sudo apt-get install -y "${MISSING_PKGS[@]}"
        echo ""
    else
        echo "   ✅ All system packages already installed."
    fi
elif [[ "$OS" == "fedora" || "$OS_LIKE" == *"fedora"* || "$OS_LIKE" == *"rhel"* ]]; then
    check_pkg_rpm() {
        if ! rpm -q "$1" &>/dev/null; then
            MISSING_PKGS+=("$1")
        fi
    }
    check_pkg_rpm "portaudio"
    check_pkg_rpm "ffmpeg"
    # Note: On some Fedora versions libsndfile might be installed but not match rpm query exactly without arch, but usually rpm -q works.
    check_pkg_rpm "libsndfile"
    check_pkg_rpm "python3-gobject"
    check_pkg_rpm "gtk4"
    check_pkg_rpm "libadwaita"

    if [ ${#MISSING_PKGS[@]} -gt 0 ]; then
        echo "   Installing missing system packages: ${MISSING_PKGS[*]}"
        echo "   (This may ask for your password)"
        echo ""
        sudo dnf install -y "${MISSING_PKGS[@]}"
        echo ""
    else
        echo "   ✅ All system packages already installed."
    fi
elif [[ "$OS" == "arch" || "$OS_LIKE" == *"arch"* ]]; then
    check_pkg_pacman() {
        if ! pacman -Qs "$1" &>/dev/null; then
            MISSING_PKGS+=("$1")
        fi
    }
    check_pkg_pacman "portaudio"
    check_pkg_pacman "ffmpeg"
    check_pkg_pacman "libsndfile"
    check_pkg_pacman "python-gobject"
    check_pkg_pacman "gtk4"
    check_pkg_pacman "libadwaita"

    if [ ${#MISSING_PKGS[@]} -gt 0 ]; then
        echo "   Installing missing system packages: ${MISSING_PKGS[@]}"
        echo "   (This may ask for your password)"
        echo ""
        sudo pacman -S --noconfirm "${MISSING_PKGS[@]}"
        echo ""
    else
        echo "   ✅ All system packages already installed."
    fi
else
    echo "   ⚠️ Unsupported OS for automatic dependency installation."
    echo "   Please ensure you have GTK4, libadwaita, portaudio, ffmpeg, and libsndfile installed."
fi

# ── Step 2: Create virtual environment ───────────────────────────
echo ""
echo "🐍 Step 2/5: Creating Python virtual environment..."

if [ -d "$VENV_DIR" ]; then
    echo "   Virtual environment already exists at $VENV_DIR"
    echo "   (delete it and re-run this script to start fresh)"
else
    # --system-site-packages is CRITICAL:
    # It lets the venv see the system-installed PyGObject/GTK4/libadwaita
    # bindings which cannot be pip-installed.
    python3 -m venv --system-site-packages "$VENV_DIR"
    echo "   ✅ Created at $VENV_DIR"
fi

# ── Step 3: Install Python dependencies ──────────────────────────
echo ""
echo "📥 Step 3/5: Installing Python dependencies..."
echo "   (This may take a few minutes on first run — PyTorch is large)"
echo ""

# Activate the venv for this script
source "$VENV_DIR/bin/activate"

# Upgrade pip first
pip install --upgrade pip --quiet

# Install CPU-only PyTorch + whisper + audio libraries
pip install \
    sounddevice \
    soundfile \
    openai-whisper \
    --extra-index-url https://download.pytorch.org/whl/cpu \
    --quiet

# Install TuxVox itself in editable mode
pip install -e "$SCRIPT_DIR" --quiet

echo ""
echo "   ✅ All Python packages installed."

# ── Step 4: Create launcher script ───────────────────────────────
echo ""
echo "🚀 Step 4/5: Creating launcher script..."

cat > "$SCRIPT_DIR/run.sh" << 'LAUNCHER'
#!/usr/bin/env bash
# Launch TuxVox using its virtual environment.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/.venv/bin/activate"
exec python3 -m tuxvox.main "$@"
LAUNCHER
chmod +x "$SCRIPT_DIR/run.sh"

echo "   ✅ Created run.sh"

# ── Step 5: Install desktop integration ──────────────────────────
echo ""
echo "🖥️  Step 5/5: Installing desktop integration..."

DESKTOP_DIR="$HOME/.local/share/applications"
ICON_DIR="$HOME/.local/share/icons/hicolor/scalable/apps"

mkdir -p "$DESKTOP_DIR"
mkdir -p "$ICON_DIR"

# Install icon
cp "$SCRIPT_DIR/data/org.tuxvox.TuxVox.svg" "$ICON_DIR/"

# Create desktop entry
cat > "$DESKTOP_DIR/org.tuxvox.TuxVox.desktop" << DESKTOP
[Desktop Entry]
Version=1.0
Name=TuxVox
Comment=TuxVox Audio Application
Exec=$SCRIPT_DIR/run.sh
Icon=org.tuxvox.TuxVox
Terminal=false
Type=Application
Categories=AudioVideo;Audio;
StartupNotify=true
StartupWMClass=org.tuxvox.TuxVox
DESKTOP

# Make the desktop file executable (sometimes required by certain desktops)
chmod +x "$DESKTOP_DIR/org.tuxvox.TuxVox.desktop"

# Update desktop database and icon cache
if command -v update-desktop-database &> /dev/null; then
    update-desktop-database "$DESKTOP_DIR"
fi
if command -v gtk-update-icon-cache &> /dev/null; then
    gtk-update-icon-cache -f -t "$HOME/.local/share/icons/hicolor" || true
fi

# Touch the applications directory to force GNOME shell to refresh its app grid
touch "$DESKTOP_DIR"

echo "   ✅ Desktop entry installed."

# ── Done ─────────────────────────────────────────────────────────
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "✅ Setup complete!"
echo ""
echo "To launch TuxVox:"
echo ""
echo "   cd $SCRIPT_DIR"
echo "   ./run.sh"
echo ""
echo "Or activate the venv manually:"
echo ""
echo "   source $VENV_DIR/bin/activate"
echo "   python3 -m tuxvox.main"
echo ""