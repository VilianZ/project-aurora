# AURORA Server - Configuration
# All server-specific constants and settings

import os

# =============================================================================
# PATHS
# =============================================================================
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_DIR = os.path.dirname(BASE_DIR)
DATA_DIR = os.path.join(PROJECT_DIR, "data")
FACES_DIR = os.path.join(DATA_DIR, "faces")
MODELS_DIR = PROJECT_DIR
MODELS_DOWNLOAD_DIR = os.path.join(PROJECT_DIR, "models")
ATTENDANCE_CSV = os.path.join(DATA_DIR, "attendance.csv")

try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(PROJECT_DIR, ".env"))
    load_dotenv(os.path.join(BASE_DIR, ".env"), override=True)
except ImportError:
    pass

# Ensure directories exist
for directory in [DATA_DIR, FACES_DIR, MODELS_DOWNLOAD_DIR]:
    os.makedirs(directory, exist_ok=True)

# =============================================================================
# SUPABASE
# =============================================================================
SUPABASE_URL = os.getenv("SUPABASE_URL", "").strip()
SUPABASE_KEY = os.getenv("SUPABASE_KEY", "").strip()

# =============================================================================
# MQTT
# =============================================================================
MQTT_BROKER_HOST = os.getenv("MQTT_BROKER_HOST", "broker.hivemq.com")
MQTT_BROKER_PORT = int(os.getenv("MQTT_BROKER_PORT", "1883"))

# MQTT Topics (prefixed for public broker — avoid collisions)
MQTT_TOPIC_PREFIX = os.getenv("MQTT_TOPIC_PREFIX", "aurora-demo").strip().strip("/")
MQTT_TOPIC_SENSOR = f"{MQTT_TOPIC_PREFIX}/sensor"
MQTT_TOPIC_STATUS = f"{MQTT_TOPIC_PREFIX}/status"
MQTT_TOPIC_COMMAND = f"{MQTT_TOPIC_PREFIX}/command"

# =============================================================================
# ESP32 STREAM (WebSocket Push)
# =============================================================================
# ESP32 connects TO the server via WebSocket — no URL needed
# The ESP32 pushes JPEG frames to /ws/esp32-stream
ESP32_STREAM_MODE = os.getenv("ESP32_STREAM_MODE", "websocket")  # "websocket" or "mock"

# =============================================================================
# FACE RECOGNITION SETTINGS
# =============================================================================
MODEL_NAME = "buffalo_m"           # SCRFD-2.5GF + ResNet50 (same accuracy as buffalo_l, 4x lighter detector)
DETECTION_SIZE = (320, 320)        # Sufficient for near-field faces, ~4x faster than (640,640)
RECOGNITION_THRESHOLD = 0.45
SIMILARITY_THRESHOLD = 0.3

# ONNX Runtime providers
PREFERRED_PROVIDERS = ['DmlExecutionProvider', 'CPUExecutionProvider']
FALLBACK_PROVIDERS = ['CPUExecutionProvider']

# =============================================================================
# SENSOR SETTINGS
# =============================================================================
# Distance threshold (cm) — trigger recognition when someone is this close
SENSOR_DISTANCE_THRESHOLD = 150.0

# =============================================================================
# ATTENDANCE SETTINGS
# =============================================================================
ATTENDANCE_COOLDOWN = 30  # seconds before same person can be logged again
UNKNOWN_LOG_COOLDOWN = 300  # 5 minutes — global cooldown for unknown face logging

# =============================================================================
# SERVER SETTINGS
# =============================================================================
SERVER_HOST = os.getenv("SERVER_HOST", "0.0.0.0")
SERVER_PORT = int(os.getenv("SERVER_PORT", "8000"))
