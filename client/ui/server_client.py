# AURORA - Server Client
# WebSocket + REST client for connecting Tkinter GUI to the FastAPI server

import json
import queue
import threading
import time
import urllib.request
import urllib.error
from typing import Optional, List, Dict, Any


class ServerClient:
    """
    Client that connects the Tkinter GUI to the FastAPI server.
    
    - WebSocket thread receives frames (binary) + recognition overlay (JSON)
    - REST methods for face registration, deletion, listing
    """
    
    def __init__(self, server_url: str = "http://127.0.0.1:8000"):
        self.server_url = server_url.rstrip("/")
        self.ws_url = server_url.replace("http://", "ws://").replace("https://", "wss://")
        
        # Frame queue (same interface as VideoThread)
        self.frame_queue = queue.Queue(maxsize=3)
        
        # Latest recognition overlay data
        self._latest_overlay: Dict[str, Any] = {"faces": [], "sensor": {}}
        self._overlay_lock = threading.Lock()
        
        # Connection state
        self.is_connected = False
        self.is_running = False
        self._ws_thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        
        # FPS tracking
        self._frame_count = 0
        self._fps_start = time.time()
        self.fps = 0.0
        
        # Server status cache
        self.server_status: Dict[str, Any] = {}
    
    def connect(self) -> bool:
        """Start WebSocket connection to server in a background thread."""
        if self.is_running:
            return True
        
        # First, verify server is reachable
        try:
            self._http_get("/")
            print("[ServerClient] ✓ Server reachable")
        except Exception as e:
            print(f"[ServerClient] ✗ Server not reachable: {e}")
            return False
        
        # Start WebSocket thread
        self._stop_event.clear()
        self.is_running = True
        self._ws_thread = threading.Thread(target=self._ws_loop, daemon=True)
        self._ws_thread.start()
        return True
    
    def disconnect(self):
        """Stop WebSocket connection."""
        self._stop_event.set()
        self.is_running = False
        if self._ws_thread:
            self._ws_thread.join(timeout=3)
            self._ws_thread = None
        self.is_connected = False
        print("[ServerClient] Disconnected")
    
    def _ws_loop(self):
        """Background thread: WebSocket receive loop."""
        try:
            import websockets.sync.client as ws_client
        except ImportError:
            print("[ServerClient] ✗ 'websockets' package not installed!")
            print("  Install with: pip install websockets")
            self.is_running = False
            return
        
        ws_endpoint = f"{self.ws_url}/ws/feed"
        print(f"[ServerClient] Connecting to {ws_endpoint}...")
        
        while not self._stop_event.is_set():
            try:
                with ws_client.connect(ws_endpoint) as ws:
                    self.is_connected = True
                    print("[ServerClient] ✓ WebSocket connected")
                    
                    while not self._stop_event.is_set():
                        try:
                            msg = ws.recv(timeout=1.0)
                        except TimeoutError:
                            continue
                        
                        if isinstance(msg, bytes):
                            # Binary = JPEG frame
                            self._enqueue_frame(msg)
                        elif isinstance(msg, str):
                            # Text = JSON overlay or event
                            self._handle_json(msg)
                            
            except Exception as e:
                if not self._stop_event.is_set():
                    self.is_connected = False
                    print(f"[ServerClient] WebSocket error: {e}, reconnecting in 2s...")
                    time.sleep(2)
        
        self.is_connected = False
    
    def _enqueue_frame(self, jpeg_bytes: bytes):
        """Put JPEG frame in the queue (drop oldest if full)."""
        import cv2
        import numpy as np
        
        # Decode JPEG to numpy array
        arr = np.frombuffer(jpeg_bytes, dtype=np.uint8)
        frame = cv2.imdecode(arr, cv2.IMREAD_COLOR)
        
        if frame is None:
            return
        
        frame_data = {
            "display_frame": frame,
            "detection_frame": frame,  # Server already uses detection-size frames
            "jpeg_bytes": jpeg_bytes,
            "timestamp": time.time()
        }
        
        # Non-blocking put — drop old frames if full
        if self.frame_queue.full():
            try:
                self.frame_queue.get_nowait()
            except queue.Empty:
                pass
        
        try:
            self.frame_queue.put_nowait(frame_data)
        except queue.Full:
            pass
        
        # FPS tracking
        self._frame_count += 1
        elapsed = time.time() - self._fps_start
        if elapsed >= 1.0:
            self.fps = self._frame_count / elapsed
            self._frame_count = 0
            self._fps_start = time.time()
    
    def _handle_json(self, text: str):
        """Handle JSON messages from WebSocket."""
        try:
            data = json.loads(text)
            msg_type = data.get("type", "")
            
            if msg_type == "overlay":
                with self._overlay_lock:
                    self._latest_overlay = data
            elif msg_type == "recognition":
                # Recognition event — could show notification
                pass
        except json.JSONDecodeError:
            pass
    
    def get_overlay(self) -> Dict[str, Any]:
        """Get latest recognition overlay data (thread-safe)."""
        with self._overlay_lock:
            return dict(self._latest_overlay)
    
    def get_fps(self) -> float:
        """Get current FPS."""
        return self.fps
    
    # =========================================================================
    # REST API METHODS
    # =========================================================================
    
    # Headers to bypass ngrok free tier interstitial page
    _default_headers = {"ngrok-skip-browser-warning": "true", "User-Agent": "SmartSentinel/1.0"}

    def _http_get(self, path: str) -> Any:
        """Make a GET request to the server."""
        url = f"{self.server_url}{path}"
        req = urllib.request.Request(url, headers=self._default_headers)
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read().decode())
    
    def _http_delete(self, path: str) -> Any:
        """Make a DELETE request to the server."""
        url = f"{self.server_url}{path}"
        req = urllib.request.Request(url, method="DELETE", headers=self._default_headers)
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read().decode())
    
    def get_faces(self) -> List[Dict]:
        """Get list of registered faces from server."""
        try:
            data = self._http_get("/api/faces")
            # Server returns {"data": [...], "count": N}
            if isinstance(data, dict):
                return data.get("data", data.get("faces", []))
            elif isinstance(data, list):
                return data
            return []
        except Exception as e:
            print(f"[ServerClient] Get faces error: {e}")
            return []
    
    def get_stats(self) -> Dict:
        """Get attendance statistics from server."""
        try:
            return self._http_get("/api/stats")
        except Exception as e:
            print(f"[ServerClient] Get stats error: {e}")
            return {}
    
    def get_server_status(self) -> Dict:
        """Get server root status."""
        try:
            self.server_status = self._http_get("/")
            return self.server_status
        except Exception as e:
            print(f"[ServerClient] Status error: {e}")
            return {}
    
    def register_face(self, name: str, face_class: str, jpeg_bytes: bytes) -> bool:
        """
        Register a new face via the server API.
        
        Sends a multipart POST to /api/register with:
        - name (form field)
        - face_class (form field)
        - file (JPEG image)
        """
        import io
        
        url = f"{self.server_url}/api/register"
        boundary = "----FormBoundary7MA4YWxkTrZu0gW"
        
        # Build multipart form data
        body = io.BytesIO()
        
        # Name field
        body.write(f"--{boundary}\r\n".encode())
        body.write(b'Content-Disposition: form-data; name="name"\r\n\r\n')
        body.write(f"{name}\r\n".encode())
        
        # Class field (server expects "class" via Form alias)
        body.write(f"--{boundary}\r\n".encode())
        body.write(b'Content-Disposition: form-data; name="class"\r\n\r\n')
        body.write(f"{face_class}\r\n".encode())
        
        # File field
        body.write(f"--{boundary}\r\n".encode())
        body.write(b'Content-Disposition: form-data; name="image"; filename="face.jpg"\r\n')
        body.write(b"Content-Type: image/jpeg\r\n\r\n")
        body.write(jpeg_bytes)
        body.write(b"\r\n")
        
        # End boundary
        body.write(f"--{boundary}--\r\n".encode())
        
        data = body.getvalue()
        
        req = urllib.request.Request(
            url,
            data=data,
            method="POST",
            headers={"Content-Type": f"multipart/form-data; boundary={boundary}"}
        )
        
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                result = json.loads(resp.read().decode())
                return resp.status == 200 and "name" in result
        except Exception as e:
            print(f"[ServerClient] Register error: {e}")
            return False
    
    def delete_face(self, name: str) -> bool:
        """Delete a face from the server."""
        try:
            from urllib.parse import quote
            result = self._http_delete(f"/api/faces/{quote(name, safe='')}")
            return True
        except Exception as e:
            print(f"[ServerClient] Delete error: {e}")
            return False
