# AURORA Server - MJPEG Stream Receiver
# Fetches MJPEG stream from ESP32 and provides thread-safe frame access

import threading
import time
import cv2
import numpy as np
from typing import Optional

from server import config


class StreamReceiver:
    """
    Receives MJPEG stream from ESP32 camera over HTTP.
    Stores the latest frame in memory for recognition + WebSocket forwarding.
    
    Runs in a background thread to avoid blocking FastAPI.
    """

    def __init__(self):
        self._latest_frame: Optional[bytes] = None  # Raw JPEG bytes
        self._latest_numpy: Optional[np.ndarray] = None  # Decoded BGR frame
        self._lock = threading.Lock()
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._connected = False
        self._stream_url = ""  # Set by subclass or unused for WebSocket mode
        self._fps = 0.0
        self._frame_count = 0

    @property
    def is_connected(self) -> bool:
        return self._connected

    @property
    def fps(self) -> float:
        return self._fps

    def start(self):
        """Start the stream receiver in a background thread."""
        if self._running:
            return

        self._running = True
        self._thread = threading.Thread(target=self._receive_loop, daemon=True)
        self._thread.start()
        print(f"[Stream] ✓ Started receiver for {self._stream_url}")

    def stop(self):
        """Stop the stream receiver."""
        self._running = False
        if self._thread:
            self._thread.join(timeout=5)
        self._connected = False
        print("[Stream] ✓ Stopped receiver")

    def get_frame_jpeg(self) -> Optional[bytes]:
        """Get the latest frame as raw JPEG bytes (thread-safe)."""
        with self._lock:
            return self._latest_frame

    def get_frame_numpy(self) -> Optional[np.ndarray]:
        """Get the latest frame as a decoded numpy array (thread-safe)."""
        with self._lock:
            return self._latest_numpy.copy() if self._latest_numpy is not None else None

    def set_stream_url(self, url: str):
        """Update the stream URL (e.g., when ESP32 IP changes)."""
        self._stream_url = url
        print(f"[Stream] Updated URL: {url}")

    def _receive_loop(self):
        """Background thread: continuously read MJPEG stream."""
        while self._running:
            try:
                self._connect_and_read()
            except Exception as e:
                print(f"[Stream] Connection error: {e}")
                self._connected = False

            if self._running:
                print("[Stream] Reconnecting in 3 seconds...")
                time.sleep(3)

    def _connect_and_read(self):
        """Connect to MJPEG stream and read frames."""
        cap = cv2.VideoCapture(self._stream_url)

        if not cap.isOpened():
            print(f"[Stream] ✗ Cannot connect to {self._stream_url}")
            self._connected = False
            return

        print(f"[Stream] ✓ Connected to {self._stream_url}")
        self._connected = True
        self._frame_count = 0
        fps_start = time.time()

        try:
            while self._running and cap.isOpened():
                ret, frame = cap.read()
                if not ret:
                    break

                # Encode frame to JPEG
                _, jpeg = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 85])
                jpeg_bytes = jpeg.tobytes()

                # Store latest frame (thread-safe)
                with self._lock:
                    self._latest_frame = jpeg_bytes
                    self._latest_numpy = frame

                # Calculate FPS
                self._frame_count += 1
                elapsed = time.time() - fps_start
                if elapsed >= 1.0:
                    self._fps = self._frame_count / elapsed
                    self._frame_count = 0
                    fps_start = time.time()

        finally:
            cap.release()
            self._connected = False
            print("[Stream] ✗ Stream disconnected")


class MockStreamReceiver(StreamReceiver):
    """
    Mock stream receiver using laptop webcam.
    For testing when ESP32 is not available.
    """

    def __init__(self, camera_id: int = 0):
        super().__init__()
        self._camera_id = camera_id

    def _connect_and_read(self):
        """Use local webcam instead of ESP32 stream."""
        cap = cv2.VideoCapture(self._camera_id)
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)

        if not cap.isOpened():
            print(f"[MockStream] ✗ Cannot open webcam {self._camera_id}")
            self._connected = False
            return

        print(f"[MockStream] ✓ Using webcam {self._camera_id}")
        self._connected = True
        self._frame_count = 0
        fps_start = time.time()

        try:
            while self._running and cap.isOpened():
                ret, frame = cap.read()
                if not ret:
                    break

                _, jpeg = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 85])
                jpeg_bytes = jpeg.tobytes()

                with self._lock:
                    self._latest_frame = jpeg_bytes
                    self._latest_numpy = frame

                self._frame_count += 1
                elapsed = time.time() - fps_start
                if elapsed >= 1.0:
                    self._fps = self._frame_count / elapsed
                    self._frame_count = 0
                    fps_start = time.time()

                # Simulate ~15 FPS to avoid eating CPU
                time.sleep(0.066)

        finally:
            cap.release()
            self._connected = False


class WebSocketStreamReceiver(StreamReceiver):
    """
    Receives JPEG frames from ESP32 via WebSocket push.
    Replaces HTTP pull — enables cross-network operation via ngrok.
    
    Same interface as StreamReceiver:
    - get_frame_jpeg() -> bytes
    - get_frame_numpy() -> np.ndarray
    - is_connected -> bool
    - start() / stop()
    
    Performance: receive_frame() stores raw JPEG only (no decode).
    Decode happens lazily in get_frame_numpy() when a consumer needs it.
    """

    def __init__(self):
        super().__init__()
        self._stream_url = "ws-push"  # Not used, keeps interface consistent
        self._frame_count = 0
        self._fps = 0.0
        self._fps_start = time.time()
        self._frame_id = 0          # Increments on each new frame
        self._numpy_dirty = False   # True = JPEG updated, numpy stale

    @property
    def frame_id(self) -> int:
        """Current frame ID (increments on each new frame from ESP32)."""
        return self._frame_id

    def start(self):
        """No background thread needed — frames arrive via WebSocket."""
        self._running = True
        print("[WebSocketStream] ✓ Receiver ready (waiting for ESP32 connection)")

    def stop(self):
        """Stop accepting frames."""
        self._running = False
        self._connected = False
        print("[WebSocketStream] ✓ Stopped")

    def receive_frame(self, jpeg_bytes: bytes):
        """
        Called by the /ws/esp32-stream endpoint when a frame arrives.
        Stores raw JPEG only — NO cv2.imdecode() here (keeps event loop fast).
        """
        if not self._running:
            return

        # Store raw JPEG only (instant, 0ms CPU)
        with self._lock:
            self._latest_frame = jpeg_bytes
            self._numpy_dirty = True  # Mark: numpy needs re-decode
            self._frame_id += 1

        # FPS tracking
        self._frame_count += 1
        now = time.time()
        elapsed = now - self._fps_start
        if elapsed >= 1.0:
            self._fps = self._frame_count / elapsed
            self._frame_count = 0
            self._fps_start = now

    def get_frame_numpy(self) -> Optional[np.ndarray]:
        """
        Get latest frame as numpy array (lazy decode).
        Only decodes JPEG when a new frame has arrived since last call.
        Called by recognition thread — safe to block here (not on event loop).
        """
        with self._lock:
            if self._latest_frame is None:
                return None

            if self._numpy_dirty:
                # Decode only when needed (2-3x/sec instead of 15x/sec)
                nparr = np.frombuffer(self._latest_frame, np.uint8)
                frame = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
                if frame is not None:
                    self._latest_numpy = frame
                    self._numpy_dirty = False
                else:
                    return None

            return self._latest_numpy.copy() if self._latest_numpy is not None else None

    def set_connected(self, connected: bool):
        """Called by WebSocket endpoint on connect/disconnect."""
        self._connected = connected
        status = "connected" if connected else "disconnected"
        print(f"[WebSocketStream] ESP32 {status}")

