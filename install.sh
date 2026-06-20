#!/usr/bin/env bash
# install.sh

echo "Downloading TuxVox..."

# Detect OS
if [ -f /etc/os-release ]; then
    . /etc/os-release
    OS=$ID
    OS_LIKE=${ID_LIKE:-""}
else
    OS=$(uname -s)
    OS_LIKE=""
fi

# 1. Install prerequisites needed just to get the repo
echo "Installing prerequisites (git, python3)..."
if [[ "$OS" == "ubuntu" || "$OS" == "debian" || "$OS" == "kali" || "$OS_LIKE" == *"debian"* || "$OS_LIKE" == *"ubuntu"* ]]; then
    sudo apt-get update
    sudo apt-get install -y git python3-venv python3-dev build-essential
elif [[ "$OS" == "fedora" || "$OS_LIKE" == *"fedora"* || "$OS_LIKE" == *"rhel"* ]]; then
    sudo dnf install -y git python3-devel make gcc gcc-c++
elif [[ "$OS" == "arch" || "$OS_LIKE" == *"arch"* ]]; then
    sudo pacman -Syu --noconfirm git python base-devel
else
    echo "Unsupported OS for automatic prerequisite installation. Please install git and python3-venv manually."
fi

# 2. Clone the repository if it doesn't exist, otherwise update it
if [ ! -d "TuxVox" ]; then
    git clone https://github.com/CS-1313/TuxVox.git
else
    echo "TuxVox directory exists. Pulling latest updates..."
    git -C TuxVox pull
fi

# 3. Enter the directory and run the main setup
cd TuxVox
./setup.sh

# 4. Launch it!
./run.sh
