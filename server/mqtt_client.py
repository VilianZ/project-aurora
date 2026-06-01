# AURORA Server - MQTT Client
# Integrates with FastAPI via fastapi-mqtt for sensor data + actuator commands

import json
from typing import Any
from contextlib import asynccontextmanager

from fastapi_mqtt.config import MQTTConfig
from fastapi_mqtt.fastmqtt import FastMQTT
from gmqtt import Client as MQTTClient

from server import config


# =============================================================================
# MQTT CONFIGURATION
# =============================================================================

mqtt_config = MQTTConfig(
    host=config.MQTT_BROKER_HOST,
    port=config.MQTT_BROKER_PORT,
    keepalive=60,
)

fast_mqtt = FastMQTT(config=mqtt_config)


# =============================================================================
# SHARED STATE (updated by MQTT callbacks)
# =============================================================================

class SensorState:
    """Shared state for latest sensor readings and ESP32 status."""

    def __init__(self):
        self.distance_cm: float = -1  # -1 = no data
        self.esp32_online: bool = False
        self.wifi_rssi: int = 0
        self.last_sensor_update: float = 0
        self.last_status_update: float = 0

    def is_person_near(self) -> bool:
        """Check if someone is within detection range."""
        return 0 < self.distance_cm <= config.SENSOR_DISTANCE_THRESHOLD

    def to_dict(self) -> dict:
        return {
            "distance_cm": self.distance_cm,
            "esp32_online": self.esp32_online,
            "wifi_rssi": self.wifi_rssi,
            "is_person_near": self.is_person_near(),
        }


sensor_state = SensorState()


# =============================================================================
# MQTT EVENT HANDLERS
# =============================================================================

@fast_mqtt.on_connect()
async def on_connect(client: MQTTClient, flags: int, rc: int, properties: Any):
    """Called when MQTT broker connection is established."""
    client.subscribe(config.MQTT_TOPIC_SENSOR, qos=0)
    client.subscribe(config.MQTT_TOPIC_STATUS, qos=0)
    print(f"[MQTT] ✓ Connected to broker at {config.MQTT_BROKER_HOST}:{config.MQTT_BROKER_PORT}")
    print(f"[MQTT] ✓ Subscribed to: {config.MQTT_TOPIC_SENSOR}, {config.MQTT_TOPIC_STATUS}")


@fast_mqtt.on_disconnect()
async def on_disconnect(client: MQTTClient, packet, exc=None):
    """Called when MQTT broker connection is lost."""
    sensor_state.esp32_online = False
    if exc:
        print(f"[MQTT] ✗ Disconnected unexpectedly: {exc}")
    else:
        print("[MQTT] Disconnected cleanly")


@fast_mqtt.subscribe(config.MQTT_TOPIC_SENSOR, qos=0)
async def on_sensor_data(client: MQTTClient, topic: str, payload: bytes, qos: int, properties: Any):
    """
    Handle sensor distance data from ESP32.
    Topic: sentinel/sensor
    Payload: {"distance_cm": 45.2}
    """
    import time

    try:
        data = json.loads(payload.decode())
        sensor_state.distance_cm = float(data.get("distance_cm", -1))
        sensor_state.last_sensor_update = time.time()
    except (json.JSONDecodeError, ValueError) as e:
        print(f"[MQTT] Bad sensor payload: {e}")


@fast_mqtt.subscribe(config.MQTT_TOPIC_STATUS, qos=0)
async def on_status_data(client: MQTTClient, topic: str, payload: bytes, qos: int, properties: Any):
    """
    Handle status heartbeat from ESP32.
    Topic: sentinel/status
    Payload: {"state": "online", "wifi_rssi": -42}
    """
    import time

    try:
        data = json.loads(payload.decode())
        state = data.get("state", "unknown")
        sensor_state.esp32_online = (state == "online")
        sensor_state.wifi_rssi = int(data.get("wifi_rssi", 0))
        sensor_state.last_status_update = time.time()
    except (json.JSONDecodeError, ValueError) as e:
        print(f"[MQTT] Bad status payload: {e}")


# =============================================================================
# PUBLISH COMMANDS (Server → ESP32)
# =============================================================================

def send_command(action: str, name: str = "", extra: dict = None):
    """
    Publish a command to the ESP32.
    Topic: sentinel/command

    Actions:
        - "led_green": Turn on green LED (face recognized)
        - "led_red": Turn on red LED (unknown face)
        - "buzzer": Short beep
    """
    payload = {"action": action}
    if name:
        payload["name"] = name
    if extra:
        payload.update(extra)

    try:
        fast_mqtt.publish(
            config.MQTT_TOPIC_COMMAND,
            json.dumps(payload)
        )
        print(f"[MQTT] → Published command: {action}" + (f" ({name})" if name else ""))
    except (AttributeError, Exception):
        pass  # MQTT not connected yet — skip silently


def send_led_green(name: str):
    """Signal ESP32: known face recognized."""
    send_command("led_green", name=name)


def send_led_red():
    """Signal ESP32: unknown face detected."""
    send_command("led_red")


def send_buzzer():
    """Signal ESP32: beep."""
    send_command("buzzer")
