# 🔐 Project AURORA

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python 3.10+](https://img.shields.io/badge/Python-3.10%2B-blue.svg)](https://www.python.org/)
[![PlatformIO](https://img.shields.io/badge/PlatformIO-ESP32--S3-orange.svg)](https://platformio.org/)

**AU**tomated **R**ecognition **O**f **R**eal-time **A**ttendance

An AI-powered face recognition attendance system built with an ESP32-S3 camera, a FastAPI backend, and InsightFace with DirectML GPU acceleration. Point the camera, and it handles the rest — detect, recognize, and log attendance automatically.

🌐 **Live Demo:** [projectaurora.web.id](https://projectaurora.web.id)

---

## ✨ Features

- 📸 Real-time face recognition via ESP32-S3 + OV3660 camera
- 🧠 InsightFace AI with DirectML GPU acceleration
- 📡 MQTT IoT control — LEDs, buzzer, ultrasonic sensor
- 🌐 Web dashboard — live feed, attendance logs, face registration
- 🖥️ Desktop viewer — standalone GUI client
- ☁️ Supabase cloud sync (optional — works offline with CSV)
- ⚡ Setup wizard with auto network detection

---

## 📋 What You'll Need

### Hardware

- ESP32-S3 board (N16R8 recommended) with OV3660 or OV2640 camera
- HC-SR04 ultrasonic sensor
- LEDs (green, yellow, red) + active buzzer
- USB-C data cable

### Software

- Python 3.10 or newer
- PlatformIO (VSCode extension or CLI)
- Windows 10/11 with DirectX 12

> 💡 DirectML works with AMD, Intel, and NVIDIA integrated GPUs. If unavailable, the server falls back to CPU automatically.

---

## 🚀 Getting Started

```bash
# Install dependencies
pip install -r requirements.txt

# Download the AI model (~327 MB)
python scripts/download_models.py

# Generate your config files (interactive wizard)
python setup.py
```

Flash the ESP32-S3 firmware:

```bash
cd AuroraIOT
pio run -t upload
pio device monitor        # optional: watch serial output
```

Start the server:

```bash
python start.py
```

Then open the desktop client or the web dashboard:

```bash
python client/main.py              # desktop viewer
```
```bash
start Website/index.html           # or just open it in your browser
```

---

## ⚙️ Configuration

Running `python setup.py` generates three local config files (all gitignored):

| File | What it configures |
|---|---|
| `.env` | Server settings, Supabase keys, MQTT broker |
| `AuroraIOT/src/config.h` | WiFi, server IP, MQTT for the ESP32 |
| `Website/config.js` | Server URL, Supabase keys for the dashboard |

Prefer doing it manually? Just copy the templates and fill them in:

```bash
cp .env.example .env
cp AuroraIOT/src/config.example.h AuroraIOT/src/config.h
cp Website/config.example.js Website/config.js
```

---

## 🌐 Remote Access

Want to access AURORA from outside your local network? Use a tunnel:

```bash
# Cloudflare Quick Tunnel (free, no account needed)
cloudflared tunnel --url localhost:8000

# Or use ngrok
ngrok http 8000
```

Then update `config.h` with the tunnel URL and set `USE_SSL = true`, `WS_PORT = 443`.

---

## 🔌 Pin Configuration

| Component | GPIO |
|---|---|
| HC-SR04 Trigger | 1 |
| HC-SR04 Echo | 2 |
| LED Green | 38 |
| LED Yellow | 39 |
| LED Red | 40 |
| Buzzer | 41 |

Pin assignments can be changed at the top of `AuroraIOT/src/main.cpp`.
