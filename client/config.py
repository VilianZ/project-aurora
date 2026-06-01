    # Smart Sentinel - Configuration
# All constants and paths for the Face Recognition Attendance System

import os

# =============================================================================
# PATHS
# =============================================================================
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
FACES_DIR = os.path.join(DATA_DIR, "faces")
MODELS_DIR = os.path.join(BASE_DIR, "models")
ATTENDANCE_CSV = os.path.join(DATA_DIR, "attendance.csv")

# Ensure directories exist
for directory in [DATA_DIR, FACES_DIR, MODELS_DIR]:
    os.makedirs(directory, exist_ok=True)

# =============================================================================
# CAMERA SETTINGS
# =============================================================================
CAMERA_ID = 0  # Default webcam
CAMERA_WIDTH = 960  # Capture resolution width
CAMERA_HEIGHT = 540  # Capture resolution height (16:9)

# Detection frame (downscaled for faster processing)
DETECTION_WIDTH = 640
DETECTION_HEIGHT = 360

# =============================================================================
# FACE RECOGNITION SETTINGS
# =============================================================================
# InsightFace model name (buffalo_l, buffalo_s, etc.)
MODEL_NAME = "buffalo_l"

# Detection size for SCRFD (must be multiple of 32)
DETECTION_SIZE = (640, 640)

# Recognition threshold (lower = stricter matching)
# Typical range: 0.3 (very strict) to 0.6 (lenient)
RECOGNITION_THRESHOLD = 0.45

# Cosine similarity threshold for face matching
SIMILARITY_THRESHOLD = 0.3

# =============================================================================
# ONNX RUNTIME PROVIDERS
# =============================================================================
# Priority order: DirectML first (GPU), then CPU fallback
PREFERRED_PROVIDERS = ['DmlExecutionProvider', 'CPUExecutionProvider']
FALLBACK_PROVIDERS = ['CPUExecutionProvider']

# =============================================================================
# ATTENDANCE SETTINGS
# =============================================================================
# Cooldown period (seconds) before same person can be logged again
ATTENDANCE_COOLDOWN = 30

# =============================================================================
# GUI SETTINGS
# =============================================================================
# Window dimensions
WINDOW_WIDTH = 1100
WINDOW_HEIGHT = 700

# Video display dimensions
VIDEO_WIDTH = 800
VIDEO_HEIGHT = 450

# Frame update interval (milliseconds)
# Lower = smoother but more CPU usage
FRAME_UPDATE_MS = 33  # ~30 FPS target

# Theme settings
APPEARANCE_MODE = "dark"  # "dark", "light", "system"
COLOR_THEME = "blue"  # "blue", "dark-blue", "green"

# =============================================================================
# COLORS (For drawing on frames)
# =============================================================================
COLOR_KNOWN = (0, 255, 0)  # Green for recognized faces (BGR)
COLOR_UNKNOWN = (0, 0, 255)  # Red for unknown faces (BGR)
COLOR_DETECTING = (255, 165, 0)  # Orange while detecting (BGR)
COLOR_CLOSEST = (255, 255, 0)  # Cyan for closest unknown face / registration candidate (BGR)
FONT_SCALE = 0.6
FONT_THICKNESS = 2
