# AURORA Server - Live Feed & Sensor API Routes

import asyncio
import json
import cv2
import numpy as np
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from typing import List

from server.mqtt_client import sensor_state

router = APIRouter(tags=["feed"])


# Track connected WebSocket clients
_ws_clients: List[WebSocket] = []
_ws_annotated_clients: List[WebSocket] = []

# Colors for drawing (BGR)
_COLOR_KNOWN = (0, 255, 0)       # Green
_COLOR_UNKNOWN = (0, 0, 255)     # Red
_COLOR_CLOSEST = (255, 255, 0)   # Cyan


def get_stream():
    """Get stream receiver from app state."""
    from server.main import stream_receiver
    return stream_receiver


def get_latest_faces():
    """Get latest recognition results from the pipeline."""
    from server.main import _latest_faces
    return list(_latest_faces)  # Return a copy


def _draw_annotations(frame: np.ndarray, faces: list) -> np.ndarray:
    """
    Draw bounding boxes and labels on a frame.
    
    Returns a new annotated frame (does not modify original).
    """
    annotated = frame.copy()

    # Find closest unknown face (largest bbox among unknowns)
    unknown_faces = [f for f in faces if not f.get("known", False)]
    closest_unknown = None
    if unknown_faces:
        closest_unknown = max(
            unknown_faces,
            key=lambda f: (f["bbox"][2] - f["bbox"][0]) * (f["bbox"][3] - f["bbox"][1])
            if len(f.get("bbox", [])) == 4 else 0
        )

    for face in faces:
        bbox = face.get("bbox", [])
        if len(bbox) != 4:
            continue

        x1, y1, x2, y2 = [int(v) for v in bbox]
        name = face.get("name", "Unknown")
        conf = face.get("confidence", 0.0)
        known = face.get("known", False)

        if known:
            color = _COLOR_KNOWN
            label = f"{name} ({conf:.2f})"
        elif face is closest_unknown:
            color = _COLOR_CLOSEST
            label = f"[REGISTER] Unknown ({conf:.2f})"
        else:
            color = _COLOR_UNKNOWN
            label = f"Unknown ({conf:.2f})"

        thickness = 3 if face is closest_unknown else 2
        cv2.rectangle(annotated, (x1, y1), (x2, y2), color, thickness)
        cv2.putText(
            annotated, label,
            (x1, y1 - 10),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.6, color, 2
        )

    return annotated


@router.websocket("/ws/feed")
async def websocket_feed(websocket: WebSocket):
    """
    WebSocket endpoint for live camera feed + recognition data.
    
    Sends alternating messages:
    - Binary: JPEG frame bytes (RAW — no annotations)
    - Text (JSON): {"faces": [...], "sensor": {...}}
    
    Used by the desktop app which draws its own overlays.
    """
    await websocket.accept()
    _ws_clients.append(websocket)
    print(f"[WebSocket] Client connected ({len(_ws_clients)} total)")

    stream = get_stream()

    try:
        while True:
            # Get latest frame
            frame = stream.get_frame_jpeg()
            if frame is not None:
                # Send frame as binary
                await websocket.send_bytes(frame)

                # Send recognition overlay data as JSON text
                faces = get_latest_faces()
                overlay = {
                    "type": "overlay",
                    "faces": faces,
                    "sensor": sensor_state.to_dict()
                }
                await websocket.send_text(json.dumps(overlay))

            # ~24 FPS to clients
            await asyncio.sleep(0.042)

    except WebSocketDisconnect:
        pass
    except Exception as e:
        print(f"[WebSocket] Client error: {e}")
    finally:
        if websocket in _ws_clients:
            _ws_clients.remove(websocket)
        print(f"[WebSocket] Client disconnected ({len(_ws_clients)} total)")


# Shared cache for annotated frames (encode once, broadcast to all)
_annotated_cache_jpeg: bytes = b""
_annotated_cache_frame_id: int = -1
_annotated_cache_lock = asyncio.Lock()


def _build_annotated_jpeg(stream, faces) -> bytes:
    """
    CPU-heavy work: decode + draw + encode.
    Runs in thread pool to avoid blocking event loop.
    """
    frame_np = stream.get_frame_numpy()
    if frame_np is None:
        return None

    annotated = _draw_annotations(frame_np, faces)
    _, jpeg = cv2.imencode('.jpg', annotated, [cv2.IMWRITE_JPEG_QUALITY, 80])
    return jpeg.tobytes()


async def _get_cached_annotated_frame(stream) -> tuple:
    """
    Get annotated frame from cache (encode once, share with all browsers).
    CPU work runs in thread pool — event loop stays free for WebSocket I/O.
    """
    global _annotated_cache_jpeg, _annotated_cache_frame_id

    current_id = getattr(stream, 'frame_id', -1)

    async with _annotated_cache_lock:
        if current_id != _annotated_cache_frame_id or _annotated_cache_jpeg == b"":
            faces = get_latest_faces()

            # Run CPU-heavy work in thread pool (non-blocking!)
            loop = asyncio.get_running_loop()
            jpeg_bytes = await loop.run_in_executor(
                None, _build_annotated_jpeg, stream, faces
            )

            if jpeg_bytes is None:
                return None, None

            _annotated_cache_jpeg = jpeg_bytes
            _annotated_cache_frame_id = current_id

            overlay = {
                "type": "overlay",
                "faces": faces,
                "sensor": sensor_state.to_dict()
            }
            return _annotated_cache_jpeg, overlay
        else:
            overlay = {
                "type": "overlay",
                "faces": get_latest_faces(),
                "sensor": sensor_state.to_dict()
            }
            return _annotated_cache_jpeg, overlay



@router.websocket("/ws/feed/annotated")
async def websocket_feed_annotated(websocket: WebSocket):
    """
    WebSocket endpoint for ANNOTATED live feed (for website).
    
    Sends alternating messages:
    - Binary: JPEG frame bytes WITH bounding boxes + labels drawn
    - Text (JSON): {"type": "overlay", "faces": [...], "sensor": {...}}
    
    Performance: annotated frame is encoded ONCE and shared across all browsers.
    """
    await websocket.accept()
    _ws_annotated_clients.append(websocket)
    print(f"[WebSocket/Annotated] Browser connected ({len(_ws_annotated_clients)} total)")

    stream = get_stream()

    try:
        while True:
            jpeg_bytes, overlay = await _get_cached_annotated_frame(stream)

            if jpeg_bytes is not None:
                await websocket.send_bytes(jpeg_bytes)
                await websocket.send_text(json.dumps(overlay))

            # ~24 FPS for website
            await asyncio.sleep(0.042)

    except WebSocketDisconnect:
        pass
    except Exception as e:
        print(f"[WebSocket/Annotated] Client error: {e}")
    finally:
        if websocket in _ws_annotated_clients:
            _ws_annotated_clients.remove(websocket)
        print(f"[WebSocket/Annotated] Browser disconnected ({len(_ws_annotated_clients)} total)")


async def broadcast_event(event: dict):
    """
    Broadcast a recognition event to all connected WebSocket clients.
    
    Event format:
    {
        "type": "recognition",
        "name": "Hanif",
        "confidence": 0.96,
        "status": "present",
        "time": "07:15:32"
    }
    """
    all_clients = _ws_clients + _ws_annotated_clients
    if not all_clients:
        return

    message = json.dumps(event)
    disconnected = []

    for ws in all_clients:
        try:
            await ws.send_text(message)
        except Exception:
            disconnected.append(ws)

    # Clean up disconnected clients
    for ws in disconnected:
        if ws in _ws_clients:
            _ws_clients.remove(ws)
        if ws in _ws_annotated_clients:
            _ws_annotated_clients.remove(ws)


@router.websocket("/ws/esp32-stream")
async def esp32_stream_endpoint(websocket: WebSocket):
    """
    WebSocket endpoint for ESP32 to push camera frames.
    
    Receives: Binary JPEG frames from ESP32
    Protocol: ESP32 connects via WSS, sends binary frames continuously
    Server stores latest frame for recognition pipeline + output feeds.
    """
    stream = websocket.app.state.stream_receiver

    await websocket.accept()
    stream.set_connected(True)
    client_info = f"{websocket.client.host}:{websocket.client.port}" if websocket.client else "unknown"
    print(f"[ESP32 Stream] ✓ ESP32 connected from {client_info}")

    try:
        while True:
            # Receive binary JPEG frame from ESP32
            data = await websocket.receive_bytes()
            stream.receive_frame(data)
    except WebSocketDisconnect:
        print("[ESP32 Stream] ESP32 disconnected")
    except Exception as e:
        print(f"[ESP32 Stream] Error: {e}")
    finally:
        stream.set_connected(False)


@router.get("/api/sensor/status")
async def get_sensor_status():
    """
    Get latest sensor reading and ESP32 status.
    
    Returns distance, online status, WiFi signal strength.
    """
    return sensor_state.to_dict()

