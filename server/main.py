# AURORA Server - Main FastAPI Application
# Ties together: MQTT, Recognition, Database, Stream, API Routes

# Fix Windows cp1252 encoding — allow Unicode symbols (✓ ✗) in print output
import sys
if sys.stdout.encoding != 'utf-8':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
if sys.stderr.encoding != 'utf-8':
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')

import asyncio
import threading
import time
from contextlib import asynccontextmanager
from datetime import datetime

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from server import config
from server.mqtt_client import fast_mqtt, sensor_state, send_led_green, send_led_red
from server.core.recognition import FaceEngine
from server.core.database import DatabaseManager
from server.core.stream import StreamReceiver, MockStreamReceiver, WebSocketStreamReceiver


# =============================================================================
# GLOBAL INSTANCES (shared across modules)
# =============================================================================

face_engine = FaceEngine()
database = DatabaseManager()

# Use WebSocketStreamReceiver for ESP32 push via ngrok
# MockStreamReceiver(camera_id=0) for local testing with webcam
if config.ESP32_STREAM_MODE == "mock":
    stream_receiver = MockStreamReceiver(camera_id=0)
else:
    stream_receiver = WebSocketStreamReceiver()

# Recognition pipeline state
_recognition_running = False
_recognition_thread = None
_event_loop = None  # Store reference to main async event loop
_latest_faces = []  # Latest recognition results [{name, confidence, bbox}]

# Lock to prevent concurrent InsightFace access (DirectML is NOT thread-safe)
engine_lock = threading.Lock()


# =============================================================================
# RECOGNITION PIPELINE (background thread)
# =============================================================================

def _recognition_loop():
    """
    Background thread: continuously grabs frames and runs recognition
    when the ultrasonic sensor detects someone nearby.
    
    Flow:
    1. Check sensor_state → is someone near?
    2. Grab latest frame from stream
    3. Run InsightFace detection + identification
    4. Log attendance (Supabase + CSV)
    5. Send MQTT command to ESP32 (LED green/red)
    6. Broadcast result to WebSocket clients
    """
    global _recognition_running

    print("[Recognition] ✓ Pipeline started")
    
    # Throttle for unknown faces — don't spam led_red
    last_unknown_alert = 0
    UNKNOWN_ALERT_COOLDOWN = 5.0  # seconds between unknown face alerts

    # Global cooldown for unknown face activity logging (5 min)
    last_unknown_log_time = 0

    # Track last processed frame to avoid re-processing stale frames
    last_processed_frame_id = -1

    # Inference performance monitoring
    _infer_times = []
    _last_perf_log = time.time()

    while _recognition_running:
        try:
            # Gate 1: Skip AI when ultrasonic says nobody is nearby
            distance = sensor_state.distance_cm
            if distance is not None and distance > config.SENSOR_DISTANCE_THRESHOLD:
                time.sleep(0.5)  # No one near — sleep longer to save CPU
                continue

            # Gate 2: Only process when a NEW frame arrives from ESP32
            current_frame_id = getattr(stream_receiver, 'frame_id', -1)
            if current_frame_id == last_processed_frame_id and current_frame_id >= 0:
                time.sleep(0.05)  # Wait briefly for new frame
                continue

            # Grab latest frame
            frame_numpy = stream_receiver.get_frame_numpy()
            if frame_numpy is None:
                time.sleep(0.1)
                continue

            # Frame lag check (captured vs processed)
            frame_lag = current_frame_id - last_processed_frame_id if last_processed_frame_id >= 0 else 0

            last_processed_frame_id = current_frame_id

            # Run face detection with timing (locked — DirectML is not thread-safe)
            t0 = time.perf_counter()
            with engine_lock:
                result = face_engine.detect_faces(frame_numpy)
            infer_ms = (time.perf_counter() - t0) * 1000

            # Log performance periodically (every 10s)
            _infer_times.append(infer_ms)
            now_perf = time.time()
            if now_perf - _last_perf_log >= 10.0 and _infer_times:
                avg_ms = sum(_infer_times) / len(_infer_times)
                max_ms = max(_infer_times)
                print(f"[Recognition] ⏱ Avg: {avg_ms:.0f}ms | Max: {max_ms:.0f}ms | "
                      f"Frames: {len(_infer_times)} | frame_id: {current_frame_id}")
                _infer_times.clear()
                _last_perf_log = now_perf

            if not result:
                time.sleep(0.5)
                continue

            # Process each detected face
            found_known = False
            frame_faces = []  # Collect results for this frame
            for face in result:
                with engine_lock:
                    embedding = face_engine.get_embedding(face)
                if embedding is None:
                    continue

                # Identify against database
                name, confidence = face_engine.identify(
                    embedding, database.get_embeddings()
                )

                # Store bbox for WebSocket broadcast
                bbox = face.bbox.astype(int).tolist()
                face_data = {
                    "name": name or "Unknown",
                    "confidence": round(float(confidence), 4) if confidence else 0.0,
                    "bbox": bbox,
                    "known": name is not None
                }
                frame_faces.append(face_data)

                if name is not None:
                    found_known = True
                    face_cls = database.face_classes.get(name, "")

                    # Known face — log attendance and signal green
                    logged = database.log_attendance(
                        name, confidence,
                        face_class=face_cls
                    )

                    if logged:
                        attendance_status = logged  # "present" or "late"
                        send_led_green(name)
                        print(f"[Recognition] ✓ {name} ({confidence:.2f}) — {attendance_status}")

                        # Log to activity_logs
                        database.log_activity(
                            "KNOWN", name, confidence,
                            face_class=face_cls,
                            details=f"Attendance logged as {attendance_status} ({confidence:.0%})"
                        )

                        # Broadcast to WebSocket clients with actual status
                        _broadcast_recognition_event(
                            name, confidence, attendance_status
                        )

            # Update shared results for WebSocket feed
            _latest_faces[:] = frame_faces

            # Only send led_red if all faces are unknown AND cooldown elapsed
            if not found_known and result:
                now = time.time()
                if now - last_unknown_alert > UNKNOWN_ALERT_COOLDOWN:
                    send_led_red()
                    last_unknown_alert = now

                # Activity log: unknown with global 5-min cooldown
                if now - last_unknown_log_time > config.UNKNOWN_LOG_COOLDOWN:
                    last_unknown_log_time = now
                    # Pick highest confidence unknown
                    unknown_faces = [f for f in frame_faces if not f["known"]]
                    if unknown_faces:
                        best = max(unknown_faces, key=lambda f: f["confidence"])
                        database.log_activity(
                            "UNKNOWN", None, best["confidence"],
                            details=f"{len(unknown_faces)} unknown face(s) detected"
                        )
                        # Broadcast unknown activity to WebSocket
                        _broadcast_activity_event(
                            "UNKNOWN", None, best["confidence"],
                            f"{len(unknown_faces)} unknown face(s)"
                        )

            # Don't overwhelm CPU — process at ~2 FPS
            time.sleep(0.1)

        except Exception as e:
            print(f"[Recognition] Error: {e}")
            time.sleep(1)

    print("[Recognition] Pipeline stopped")


def _broadcast_recognition_event(name: str, confidence: float, status: str):
    """Send recognition event to WebSocket clients (thread-safe)."""
    global _event_loop
    try:
        from server.api.feed import broadcast_event

        event = {
            "type": "recognition",
            "name": name,
            "confidence": round(confidence, 4),
            "status": status,
            "time": datetime.now().strftime("%H:%M:%S")
        }

        # Schedule broadcast on the stored event loop
        if _event_loop and _event_loop.is_running():
            asyncio.run_coroutine_threadsafe(broadcast_event(event), _event_loop)
    except Exception as e:
        print(f"[Recognition] Broadcast error: {e}")


def _broadcast_activity_event(
    event_type: str, name: str, confidence: float, details: str
):
    """Send activity event to WebSocket clients (for live feed stream table)."""
    global _event_loop
    try:
        from server.api.feed import broadcast_event

        event = {
            "type": "activity",
            "event_type": event_type,
            "name": name,
            "confidence": round(confidence, 4) if confidence else 0.0,
            "details": details,
            "time": datetime.now().strftime("%H:%M:%S")
        }

        if _event_loop and _event_loop.is_running():
            asyncio.run_coroutine_threadsafe(broadcast_event(event), _event_loop)
    except Exception as e:
        print(f"[Recognition] Activity broadcast error: {e}")


# =============================================================================
# LIFESPAN (startup/shutdown)
# =============================================================================

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage startup and shutdown of all server components."""
    global _recognition_running, _recognition_thread, _event_loop

    # Store reference to the running event loop for cross-thread usage
    _event_loop = asyncio.get_running_loop()

    print("=" * 60)
    print("  Smart Sentinel Server — Starting Up")
    print("=" * 60)

    # 1. Start MQTT (background — gmqtt blocks the event loop on Windows)
    async def _mqtt_connect():
        try:
            await fast_mqtt.mqtt_startup()
            print("[MQTT] ✓ Connected in background")
        except Exception as e:
            print(f"[MQTT] ⚠ Background connection failed: {e}")

    asyncio.create_task(_mqtt_connect())
    print("[Startup] ✓ MQTT connecting in background...")

    # 2. Warm up InsightFace in a thread to avoid blocking the event loop
    print("[Startup] Warming up InsightFace (this may take a moment)...")
    warmup_done = threading.Event()

    def _do_warmup():
        face_engine.warmup()
        warmup_done.set()

    warmup_thread = threading.Thread(target=_do_warmup, daemon=True)
    warmup_thread.start()

    # Wait for warmup with a timeout (don't block forever)
    await asyncio.get_running_loop().run_in_executor(
        None, lambda: warmup_done.wait(timeout=120)
    )

    if face_engine.is_ready:
        print(f"[Startup] ✓ InsightFace ready ({face_engine.active_provider})")
    else:
        print("[Startup] ✗ InsightFace failed — recognition will not work")

    # 3. Start stream receiver
    stream_receiver.start()
    app.state.stream_receiver = stream_receiver  # Expose via app.state (avoids circular imports)
    print(f"[Startup] ✓ Stream receiver started ({type(stream_receiver).__name__})")

    # 4. Start recognition pipeline
    _recognition_running = True
    _recognition_thread = threading.Thread(target=_recognition_loop, daemon=True)
    _recognition_thread.start()
    print("[Startup] ✓ Recognition pipeline started")

    # 5. Load face database
    count = database.load_faces()
    print(f"[Startup] ✓ Loaded {count} registered faces")

    print("=" * 60)
    print(f"  Server running at http://{config.SERVER_HOST}:{config.SERVER_PORT}")
    print(f"  MQTT broker: {config.MQTT_BROKER_HOST}:{config.MQTT_BROKER_PORT}")
    print(f"  API docs at http://{config.SERVER_HOST}:{config.SERVER_PORT}/docs")
    print("=" * 60)

    yield  # Server is running

    # --- Shutdown ---
    print("\n[Shutdown] Stopping server...")
    _recognition_running = False
    if _recognition_thread:
        _recognition_thread.join(timeout=5)
    stream_receiver.stop()
    await fast_mqtt.mqtt_shutdown()
    print("[Shutdown] ✓ Server stopped cleanly")


# =============================================================================
# APP CREATION
# =============================================================================

app = FastAPI(
    title="AURORA API",
    description="IoT Face Recognition Attendance System",
    version="1.0.0",
    lifespan=lifespan
)

# CORS — allow dashboard to connect
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include API routers
from server.api.attendance import router as attendance_router
from server.api.faces import router as faces_router
from server.api.feed import router as feed_router

app.include_router(attendance_router)
app.include_router(faces_router)
app.include_router(feed_router)


# Root endpoint
@app.get("/")
async def root():
    return {
        "name": "Smart Sentinel Server",
        "version": "1.0.0",
        "face_engine": face_engine.get_provider_status(),
        "faces_loaded": database.get_face_count(),
        "stream_connected": stream_receiver.is_connected,
        "mqtt": {
            "esp32_online": sensor_state.esp32_online,
            "distance_cm": sensor_state.distance_cm
        }
    }
