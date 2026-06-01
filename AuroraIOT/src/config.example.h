// Copy this file to config.h and fill in your local values.
// config.h is gitignored so WiFi credentials and local URLs stay private.

#pragma once

// WiFi
const char* WIFI_SSID = "YOUR_WIFI_SSID";
const char* WIFI_PASS = "YOUR_WIFI_PASSWORD";

// MQTT broker.
// The default public broker is convenient for demos, but use your own broker
// and a unique topic prefix for real deployments.
const char* MQTT_HOST = "broker.hivemq.com";
const uint16_t MQTT_PORT = 1883;

// MQTT topics. Keep this prefix unique per installation.
const char* TOPIC_SENSOR = "aurora-demo/sensor";
const char* TOPIC_STATUS = "aurora-demo/status";
const char* TOPIC_COMMAND = "aurora-demo/command";

// WebSocket server. For Windows mobile hotspot, the host is often
// 192.168.137.1. Use your laptop/server IPv4 address if different.
const char* WS_HOST = "192.168.137.1";
const uint16_t WS_PORT = 8000;
const char* WS_PATH = "/ws/esp32-stream";
const bool USE_SSL = false;
