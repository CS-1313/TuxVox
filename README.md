<p align="center">
  <img src="data/tuxvox-logo.png" alt="TuxVox Logo" width="100%">
</p>

# 🎙 TuxVox

**A stable, simple, CPU-only speech-to-text application for Linux.**

TuxVox lets you quickly dictate text and paste it into any application. It uses [OpenAI Whisper](https://github.com/openai/whisper) running locally on your CPU — no internet connection required after the initial model download.

![License](https://img.shields.io/badge/license-AGPLv3-blue.svg)
![Platform](https://img.shields.io/badge/platform-Linux-green.svg)
![Python](https://img.shields.io/badge/python-3.11%2B-blue.svg)

> **🔒 100% Private & Offline**
> TuxVox uses a local AI model (OpenAI Whisper) that runs entirely on your computer. Your voice is processed locally, never transmitted to any server, and your voice audio is never stored after transcription is complete. The only network request TuxVox makes is an optional one-time model download. After that, it works with no internet connection — permanently.

---

## ✨ Features

- **One-click recording** — single button to start/stop recording from your microphone
- **Typewriter text output** — transcribed text flows in word-by-word with a smooth streaming effect
- **Additive editor** — each transcription appends to the previous text; edit freely
- **Clean-slate architecture** — the transcription engine is fully destroyed and rebuilt between each use, preventing state bleed and crashes
- **Smart model recommendation** — automatically detects your hardware and suggests the best Whisper model
- **Privacy first** — everything runs locally, fully offline after initial setup
- **GNOME-native UI** — built with GTK4 and libadwaita, supports light/dark mode

## 📦 Installation

### Quick Install/Update (Ubuntu, Debian, Fedora, Arch Linux, Kali)

The easiest way to install or update TuxVox is using the one-step setup script. This will automatically download TuxVox (or pull the latest updates if already installed), install the required system dependencies for your distribution, and create a virtual environment.

Open your terminal and run:

```bash
curl -sSL https://raw.githubusercontent.com/CS-1313/TuxVox/main/install.sh | bash
```

<details>
<summary><b>Manual setup (if you prefer not to use the script)</b></summary>

**1. Clone the repository**
```bash
git clone https://github.com/CS-1313/TuxVox.git ~/TuxVox
cd ~/TuxVox
```

**2. Run the setup script**
```bash
./setup.sh
```

> 💡 **Why a virtual environment?** Modern Linux distributions (like Ubuntu 24.04+ and Fedora) block system-wide pip installs ([PEP 668](https://peps.python.org/pep-0668/)). The `./setup.sh` script automatically creates a venv to keep TuxVox's dependencies isolated. It uses the `--system-site-packages` flag so the environment can access your system-installed GTK4/libadwaita Python bindings, which cannot be installed via pip.

**3. Launch TuxVox**
```bash
./run.sh
```

</details>

## 🎤 Usage

1. **Launch TuxVox** — the app opens with a clean editor and a "Start Recording" button
2. **Click "Start Recording"** — speak into your microphone
3. **Click "Stop & Transcribe"** — your speech is transcribed and streamed into the editor
4. **Copy or edit** — use "Copy All to Clipboard" to paste into any app, or edit the text directly
5. **Repeat** — each new recording appends below the previous text

## ⚙ Settings

Access settings via the gear icon in the header bar:

| Setting | Description |
|---------|-------------|
| **Transcription Model** | Choose from Tiny, Base, Small, Medium, Large, or Large V3 |
| **Input Microphone** | Select which microphone to use |
| **Spoken Language** | Set your language or use Auto-Detect |
| **Text Appearance Speed** | Control the typewriter effect speed |
| **Show Word Confidence** | Dim uncertain words for accuracy review |
| **Include Punctuation** | Toggle automatic punctuation |
| **Save Transcriptions** | Optionally save to daily text files |

### Model Comparison

| Model | Speed | Accuracy | RAM |
|-------|-------|----------|-----|
| Tiny | ⚡ Fastest | ★★☆☆☆ | ~150 MB |
| Base | 🚀 Fast | ★★★☆☆ | ~300 MB |
| Small | 🔄 Balanced | ★★★★☆ | ~500 MB |
| Medium | 🐢 Slower | ★★★★★ | ~1.5 GB |
| Large | 🐌 Slow | ★★★★★+ | ~3 GB |
| Large V3 | 🐌 Slow | ★★★★★+ | ~3 GB |

Use **"Recommend Best Model for My Computer"** in Settings to get a personalized suggestion.

## 🧪 Experimental Mode — Global Hotkey & Inline Typing

Experimental Mode lets you dictate into **any** application from anywhere on
your desktop: press a global hotkey, speak, press it again, and the
transcribed text is typed directly into whatever window you were using (e.g.
a text editor, browser, or chat app). It works on both X11 and **Wayland**
(including GNOME on Wayland).

### How it works

- **Global hotkey** is detected by reading your keyboard input devices
  directly (`/dev/input/event*` via `evdev`). This is the only reliable way
  to capture a shortcut on Wayland, where ordinary apps cannot see key
  presses sent to other windows.
- **Inline typing** is done by injecting keystrokes at the kernel level
  (`/dev/uinput`). This bypasses the display server entirely, so the text
  lands in whichever window currently has focus — no clipboard, no portals.
- **Audio chimes** signal start, stop, completion, and errors. In inline
  mode no on-screen overlay is shown, because presenting a window on Wayland
  would steal focus from your target app and the text would go nowhere. The
  chimes are your feedback instead:
  - **Start** (rising tone) — dictation is now recording
  - **Stop** (falling tone) — recording stopped, transcribing
  - **Complete** — text was typed into your app
  - **Error** — something went wrong (falls back to the TuxVox panel)

### One-time setup

Inline typing needs write access to `/dev/uinput`, which is root-only by
default. A helper script grants your user access via the `input` group and a
udev rule. Run it **once**:

```bash
sudo bash ~/TuxVox/scripts/setup-uinput.sh
```

This will:

1. Load the `uinput` kernel module (and ensure it loads on every boot).
2. Add your user to the `input` group.
3. Install a udev rule (`/etc/udev/rules.d/99-tuxvox-uinput.rules`) so
   `/dev/uinput` is group-writable by `input`.
4. Apply the new permissions immediately.

> **Important:** If the script adds you to the `input` group for the first
> time, you must **reboot your computer** for the change to take
> effect. Then restart TuxVox.

Reading the keyboard for the global hotkey also relies on `input` group
membership, so the same one-time step enables both halves of the feature.

> **Note for X11 users:** On an X11 session, inline typing can alternatively
> use `xdotool` (`sudo apt install xdotool`). TuxVox prefers the
> `uinput` path when available because it also works on Wayland.

### Using it

1. Open **Settings → Experimental** and enable **Experimental Mode**.
2. Set your **Output Mode** to **Inline** and choose a **Global Hotkey**
   (default `Ctrl+Shift+L`).
3. Click into any application where you want to type.
4. Press the hotkey — you'll hear the **start** chime. Speak.
5. Press the hotkey again — you'll hear the **stop** chime, then the
   **complete** chime once the text has been typed into your app.

> **Tip:** Avoid choosing a hotkey that clashes with a common system or app
> shortcut. TuxVox warns about well-known conflicts.

### Troubleshooting

| Symptom | Fix |
|---------|-----|
| General bugs or weird behavior | 1. Fully close the application. <br>2. Restart your computer. <br>3. Rerun the curl installation/update script to ensure you have the latest files. |
| General Wipe and Reinstall | If basic troubleshooting fails, you can completely reset TuxVox (if it is installed in your home directory — change path if needed). <br><br>⚠️ **Warning:** This will delete your custom settings, as well as any saved transcriptions if you chose to save them inside the `~/TuxVox` directory. <br><br>`rm -rf ~/TuxVox && rm -rf ~/.config/tuxvox && curl -sSL https://raw.githubusercontent.com/CS-1313/TuxVox/main/install.sh \| bash` |
| Hotkey does nothing | Confirm you are in the `input` group (`groups \| grep input`); reboot your computer after running the setup script. |
| Nothing is typed | `/dev/uinput` isn't writable — download and run `setup-uinput.sh` with sudo, then reboot your computer. Check logs for an "inline typing unavailable" warning. |
| Text goes to the wrong window | Make sure the target window has focus before pressing the hotkey; the inline overlay is intentionally suppressed so focus stays put. |
| Some characters are missing | Inline typing uses a US keyboard layout; characters outside that layout are skipped. |

## 🗑 Uninstalling

If you ever need to completely remove TuxVox and all of its traces from your computer:

**1. Remove the application:**
Simply delete the folder you cloned (change path if needed):
```bash
rm -rf ~/TuxVox
```

**2. Remove configuration:**
TuxVox saves your preferences in your configuration folder. To wipe this data:
```bash
rm -rf ~/.config/tuxvox
```

**3. Remove Experimental Mode permissions (Optional):**
If you ran the `setup-uinput.sh` script to enable inline typing, you can remove the permissions it created:
```bash
sudo rm /etc/udev/rules.d/99-tuxvox-uinput.rules
sudo udevadm control --reload-rules
sudo udevadm trigger
```
> **Note:** The script also added your user to the `input` group. You can safely remain in this group, but if you wish to remove yourself, you can run `sudo gpasswd -d $USER input` and reboot your computer.

## 🐛 Bug Reports

Found a bug? Use the **Help & Diagnostics** section in Settings to copy your diagnostic log (with optional redaction of your speech), then [open an issue on GitHub](https://github.com/CS-1313/TuxVox/issues/new?template=bug_report.md).

## 📄 License

GNU Affero General Public License v3.0 — see [LICENSE](LICENSE) for details.
