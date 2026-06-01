# Contributing to Project AURORA

Thanks for your interest in improving Project AURORA! Here's how you can help.

---

## 🐛 Reporting Bugs

1. Check [existing issues](../../issues) first to avoid duplicates
2. Open a new issue with:
   - **Description** — What happened vs what you expected
   - **Steps to reproduce** — Minimal steps to trigger the bug
   - **Environment** — OS, Python version, ESP32 board model, GPU info
   - **Logs** — Server console output, ESP32 Serial Monitor output

## 💡 Suggesting Features

Open an issue with the `enhancement` label. Describe:
- The problem you're trying to solve
- Your proposed solution
- Any alternatives you considered

---

## 🛠️ Development Setup

### Prerequisites

- Python 3.10 or newer
- PlatformIO (for ESP32 firmware)
- Git

### Setup

```bash
# Clone the repo
git clone https://github.com/VilianZ/project-aurora.git
cd project-aurora

# Create a virtual environment (recommended)
python -m venv venv
venv\Scripts\activate        # Windows
# source venv/bin/activate   # Linux/Mac

# Install dependencies
pip install -r requirements.txt

# Download the AI model
python scripts/download_models.py

# Generate local config files
python setup.py

# Start the server
python start.py
```

---

## 📝 Code Guidelines

### General

- Keep code readable — prefer clarity over cleverness
- Add comments for non-obvious logic
- Update documentation when changing behavior

### Python (Server)

- Follow PEP 8 style
- Use type hints where practical
- Keep functions focused — one function, one job
- Use `async` for I/O operations in FastAPI

### C++ (Firmware)

- Use descriptive `#define` names for pin assignments
- Keep hardware-specific values in `config.h` (not hardcoded in `main.cpp`)
- Use `Serial.printf()` for debug logging with `[TAG]` prefixes

### JavaScript (Website)

- Use `textContent` instead of `innerHTML` when inserting user-supplied data
- Keep Supabase credentials in `config.js` (never hardcode)

---

## 📂 What NOT to Commit

These files are **gitignored** for a reason — never commit them:

| File | Why |
|---|---|
| `.env` | Contains your Supabase keys and server config |
| `AuroraIOT/src/config.h` | Contains WiFi password and server IP |
| `Website/config.js` | Contains Supabase keys and server URL |
| `data/faces/*.npy` | Biometric face embeddings (privacy-sensitive) |
| `data/faces/face_classes.json` | Maps names to face data |
| `data/attendance.csv` | Personal attendance records |
| `models/` | Large model files (~327 MB) — use download script |
| `.pio/` | PlatformIO build artifacts |
| `__pycache__/` | Python bytecode cache |

---

## 🔀 Pull Request Process

1. **Fork** the repository
2. **Create a branch** for your feature/fix:
   ```bash
   git checkout -b feature/my-improvement
   ```
3. **Make your changes** — keep commits focused and descriptive
4. **Test** your changes:
   - Server starts without errors
   - ESP32 connects and streams successfully
   - Dashboard displays correctly
5. **Push** and open a Pull Request:
   - Describe what you changed and why
   - Link any related issues
   - Include screenshots for UI changes

---

## 🏗️ Project Architecture

Understanding the codebase:

```
ESP32 Firmware (AuroraIOT/)
  → Captures JPEG frames from camera
  → Sends frames via WebSocket to server
  → Reads ultrasonic sensor for presence detection
  → Receives MQTT commands for LED/buzzer control

Server (server/)
  → Receives frames via WebSocket (api/feed.py)
  → Decodes + runs face detection/recognition (core/recognition.py)
  → Logs attendance to Supabase or CSV (core/database.py)
  → Sends MQTT commands back to ESP32 (mqtt_client.py)
  → Serves annotated live feed to browser clients (api/feed.py)

Website (Website/)
  → Static HTML/CSS/JS dashboard
  → Connects to server via HTTP API + WebSocket
  → Displays live feed, attendance logs, face management

Desktop Client (client/)
  → Standalone GUI using CustomTkinter
  → Connects to server to view feed remotely
```

---

## 🔮 Known Areas for Improvement

These are documented for future work — great places to contribute!

- **Security hardening** — input sanitization, CORS restriction, API auth, frame limits
- **Performance** — model quantization, async inference pipeline
- **Testing** — unit tests for server API endpoints
- **Cross-platform** — Linux/Mac support for DirectML alternative (OpenVINO/CoreML)
- **UI/UX** — responsive mobile design, dark/light theme toggle
- **Deployment** — Docker support, systemd service file

---

## ⚖️ License

By contributing, you agree that your contributions will be licensed under the [MIT License](LICENSE).
