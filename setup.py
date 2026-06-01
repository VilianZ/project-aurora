#!/usr/bin/env python3
"""Generate local Project AURORA configuration files."""

from __future__ import annotations

import secrets
import socket
from pathlib import Path


ROOT = Path(__file__).resolve().parent


def prompt(label: str, default: str = "", secret: bool = False) -> str:
    suffix = f" [{default}]" if default else ""
    value = input(f"{label}{suffix}: ").strip()
    return value or default


def guess_server_ip() -> str:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("8.8.8.8", 80))
            ip = s.getsockname()[0]
        return ip
    except OSError:
        return "192.168.137.1"


def write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    print(f"  wrote {path.relative_to(ROOT)}")


def main() -> None:
    print("AURORA Setup Wizard")
    print("=" * 40)

    guessed_ip = guess_server_ip()
    mqtt_prefix = f"aurora-{secrets.token_hex(2)}"

    print("\nWiFi")
    wifi_ssid = prompt("SSID")
    wifi_pass = prompt("Password")

    print("\nServer")
    server_ip = prompt("Server IP", guessed_ip)
    server_port = prompt("Server port", "8000")

    print("\nSupabase (optional, press Enter to skip)")
    supabase_url = prompt("Supabase URL")
    supabase_key = prompt("Supabase anon key")

    print("\nMQTT")
    mqtt_host = prompt("Broker host", "broker.hivemq.com")
    mqtt_port = prompt("Broker port", "1883")
    mqtt_prefix = prompt("Topic prefix", mqtt_prefix)

    write(
        ROOT / ".env",
        f"""SUPABASE_URL={supabase_url}
SUPABASE_KEY={supabase_key}
SERVER_HOST=0.0.0.0
SERVER_PORT={server_port}
ESP32_STREAM_MODE=websocket
MQTT_BROKER_HOST={mqtt_host}
MQTT_BROKER_PORT={mqtt_port}
MQTT_TOPIC_PREFIX={mqtt_prefix}
""",
    )

    write(
        ROOT / "AuroraIOT" / "src" / "config.h",
        f"""#pragma once

const char* WIFI_SSID = "{wifi_ssid}";
const char* WIFI_PASS = "{wifi_pass}";

const char* MQTT_HOST = "{mqtt_host}";
const uint16_t MQTT_PORT = {mqtt_port};

const char* TOPIC_SENSOR = "{mqtt_prefix}/sensor";
const char* TOPIC_STATUS = "{mqtt_prefix}/status";
const char* TOPIC_COMMAND = "{mqtt_prefix}/command";

const char* WS_HOST = "{server_ip}";
const uint16_t WS_PORT = {server_port};
const char* WS_PATH = "/ws/esp32-stream";
const bool USE_SSL = false;
""",
    )

    write(
        ROOT / "Website" / "config.js",
        f"""window.AURORA_CONFIG = {{
    SUPABASE_URL: "{supabase_url}",
    SUPABASE_KEY: "{supabase_key}",
    SERVER_URL: "http://{server_ip}:{server_port}",
    WS_BASE: "ws://{server_ip}:{server_port}"
}};
""",
    )

    print("\nDone. Next steps:")
    print("  pip install -r requirements.txt")
    print("  python scripts/download_models.py")
    print("  python start.py")


if __name__ == "__main__":
    main()
