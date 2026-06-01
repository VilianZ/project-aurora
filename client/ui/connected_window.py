# AURORA - Connected Window (Server-Linked GUI)
# Subclass of SmartSentinelApp that gets frames and recognition
# from the FastAPI server instead of local camera + engine.

import os
import sys
import queue
import time
import cv2
import numpy as np
from PIL import Image
from typing import Optional

import customtkinter as ctk

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config
from ui.main_window import SmartSentinelApp
from ui.server_client import ServerClient


class ConnectedSentinelApp(SmartSentinelApp):
    """
    Server-connected version of SmartSentinelApp.
    
    Instead of running recognition locally, this GUI:
    - Receives frames + recognition overlays from the FastAPI server via WebSocket
    - Sends registration/deletion requests to the server via REST API
    - Shows server, MQTT, and sensor status in the status bar
    
    For competition showcase: demonstrates client-server architecture.
    """
    
    def __init__(self, server_url: str = "http://localhost:8000"):
        self.server_url = server_url
        self.server_client = ServerClient(server_url)
        
        # Call parent __init__ (builds UI, but we'll override behavior)
        super().__init__()
        
        # Cache for latest frame (avoids queue race in registration)
        self._latest_frame = None
        
        # Override the title to indicate server mode
        self.title("Smart Sentinel - Connected to Server")
        
        # Replace subtitle
        self.subtitle.configure(text=f"Server: {server_url}")
        
        # Override camera button labels
        self.start_btn.configure(text="Connect to Server")
        self.stop_btn.configure(text="Disconnect")
    
    def _initialize_engine(self):
        """Override: connect to server instead of local warmup."""
        self.provider_label.configure(text="Server: Connecting...")
        self.update_idletasks()
        
        # Try to connect and get server status
        try:
            status = self.server_client.get_server_status()
            if status:
                engine = status.get("face_engine", "Unknown")
                faces = status.get("faces_loaded", 0)
                mqtt = status.get("mqtt", {})
                esp32 = "🟢" if mqtt.get("esp32_online") else "🔴"
                
                self.provider_label.configure(
                    text=f"Server: {engine} | {esp32} ESP32"
                )
                print(f"[Connected] Server status: {status}")
            else:
                self.provider_label.configure(text="Server: ⚠️ Not reachable")
        except Exception as e:
            self.provider_label.configure(text=f"Server: ❌ {e}")
        
        # Update face count from server
        self._update_face_count()
    
    def _start_camera(self):
        """Override: connect to server WebSocket instead of local camera."""
        if self.is_camera_active:
            return
        
        # Clear queue
        while not self.server_client.frame_queue.empty():
            try:
                self.server_client.frame_queue.get_nowait()
            except queue.Empty:
                break
        
        # Point our frame_queue to the server client's queue
        self.frame_queue = self.server_client.frame_queue
        
        # Connect WebSocket
        success = self.server_client.connect()
        if not success:
            self.camera_status_label.configure(text="Server: 🔴 Failed")
            return
        
        self.is_camera_active = True
        self.start_btn.configure(state="disabled")
        self.stop_btn.configure(state="normal")
        self.camera_status_label.configure(text="Server: 🟢 Connected")
        
        # Start frame update loop
        self._update_frame()
    
    def _stop_camera(self):
        """Override: disconnect from server instead of stopping camera."""
        if not self.is_camera_active:
            return
        
        self.is_camera_active = False
        self.server_client.disconnect()
        
        self.start_btn.configure(state="normal")
        self.stop_btn.configure(state="disabled")
        self.camera_status_label.configure(text="Server: ⚫ Disconnected")
        
        # Reset video display
        self.video_label.configure(
            image=None,
            text="🔗 Server Mode\n\nClick 'Connect to Server' to start"
        )
    
    def _update_frame(self):
        """
        Override: display frames from server with recognition overlays.
        
        Instead of running InsightFace locally, we use the overlay data
        (bboxes, names, confidence) sent by the server via WebSocket.
        """
        if not self.is_camera_active:
            return
        
        try:
            # Get latest frame from server
            frame_data = self.frame_queue.get_nowait()
            self._latest_frame = frame_data  # Cache for registration
            display_frame = frame_data['display_frame'].copy()
            
            # Get recognition overlay from server
            overlay = self.server_client.get_overlay()
            faces = overlay.get("faces", [])
            sensor = overlay.get("sensor", {})
            
            # Find the closest (largest) unknown face for registration candidate
            unknown_faces = [f for f in faces if not f.get("known", False) and len(f.get("bbox", [])) == 4]
            closest_unknown = None
            if unknown_faces:
                # Pick the one with largest bbox area
                def face_area(f):
                    b = f["bbox"]
                    return (b[2] - b[0]) * (b[3] - b[1])
                closest_unknown = max(unknown_faces, key=face_area)
            
            # Draw bounding boxes from server recognition data
            for face_info in faces:
                bbox = face_info.get("bbox", [])
                name = face_info.get("name", "Unknown")
                conf = face_info.get("confidence", 0.0)
                known = face_info.get("known", False)
                
                if len(bbox) == 4:
                    x1, y1, x2, y2 = [int(v) for v in bbox]
                    
                    if known:
                        color = config.COLOR_KNOWN  # Green
                        label = f"{name} ({conf:.2f})"
                        
                        # Show recognition in status bar
                        self.recognized_name = name
                        self.recognition_label.configure(
                            text=f"Recognized: {name} ({conf:.2f})"
                        )
                    elif face_info is closest_unknown:
                        color = config.COLOR_CLOSEST  # Cyan — registration candidate
                        label = "Closest Face"
                    else:
                        color = config.COLOR_UNKNOWN  # Red
                        label = f"Unknown ({conf:.2f})"
                    
                    # Draw bbox and label
                    cv2.rectangle(display_frame, (x1, y1), (x2, y2), color, 2)
                    cv2.putText(
                        display_frame, label,
                        (x1, y1 - 10),
                        cv2.FONT_HERSHEY_SIMPLEX,
                        config.FONT_SCALE,
                        color,
                        config.FONT_THICKNESS
                    )
            
            # Update sensor info in status (if available)
            distance = sensor.get("distance_cm", -1)
            if distance >= 0:
                self.recognition_label.configure(
                    text=f"Sensor: {distance:.0f}cm | "
                         f"{'🟢 ESP32' if sensor.get('esp32_online') else '🔴 ESP32'}"
                )
            
            # Convert to PhotoImage for display
            display_frame = cv2.cvtColor(display_frame, cv2.COLOR_BGR2RGB)
            
            # Resize to fit display area
            h, w = display_frame.shape[:2]
            max_w, max_h = config.VIDEO_WIDTH, config.VIDEO_HEIGHT
            
            if w > max_w or h > max_h:
                ratio = min(max_w / w, max_h / h)
                new_w, new_h = int(w * ratio), int(h * ratio)
                display_frame = cv2.resize(display_frame, (new_w, new_h))
            
            image = Image.fromarray(display_frame)
            photo = ctk.CTkImage(
                light_image=image, dark_image=image,
                size=(image.width, image.height)
            )
            
            self.video_label.configure(image=photo, text="")
            self.video_label.image = photo  # Keep reference
            
            # Update FPS from server client
            fps = self.server_client.get_fps()
            self.fps_label.configure(text=f"FPS: {fps:.1f} (server)")
            
        except queue.Empty:
            pass
        except Exception as e:
            print(f"[Connected] Frame update error: {e}")
        
        # Schedule next update
        if self.is_camera_active:
            self.after(config.FRAME_UPDATE_MS, self._update_frame)
    
    def _register_face(self):
        """
        Override: register face via server API instead of locally.
        
        Captures the current frame from the server, encodes it as JPEG,
        and sends it to POST /api/register.
        """
        name = self.name_entry.get().strip()
        
        if not name:
            self._show_message("Please enter a name first!", "warning")
            return
        
        if not self.is_camera_active:
            self._show_message("Connect to server first!", "warning")
            return
        
        # Use the cached latest frame (set by _update_frame every tick)
        if self._latest_frame is None:
            self._show_message("No frame available yet. Wait a moment.", "warning")
            return
        
        frame_data = self._latest_frame
        
        # Encode frame as JPEG
        if "jpeg_bytes" in frame_data:
            jpeg_bytes = frame_data["jpeg_bytes"]
        else:
            _, buf = cv2.imencode(".jpg", frame_data["display_frame"])
            jpeg_bytes = buf.tobytes()
        
        # Send to server
        self._show_message(f"Registering {name}...", "info")
        self.update_idletasks()
        
        success = self.server_client.register_face(name, "", jpeg_bytes)
        
        if success:
            self._show_message(f"✅ Registered: {name}", "success")
            self.name_entry.delete(0, "end")
            self._update_face_count()
        else:
            self._show_message(f"❌ Failed to register: {name}", "error")
    
    def _update_face_count(self):
        """Override: get face count from server."""
        faces = self.server_client.get_faces()
        count = len(faces) if isinstance(faces, list) else 0
        self.face_count_label.configure(text=f"Registered: {count} faces (server)")
        self._refresh_face_list()
    
    def _refresh_face_list(self):
        """Override: get face list from server instead of local directory."""
        # Clear existing buttons
        for btn in self._face_buttons:
            btn.destroy()
        self._face_buttons.clear()
        self._selected_face_name = None
        self.delete_btn.configure(state="disabled")
        
        # Get registered names from server
        search_query = self.search_entry.get().strip().lower()
        
        try:
            faces_data = self.server_client.get_faces()
            if isinstance(faces_data, list):
                names = sorted([f.get("name", "") for f in faces_data if f.get("name")])
            else:
                names = sorted(faces_data.get("names", []))
        except Exception:
            names = []
        
        if search_query:
            names = [n for n in names if search_query in n.lower()]
        
        for i, name in enumerate(names):
            btn = ctk.CTkButton(
                self.face_list_frame,
                text=f"👤 {name}",
                anchor="w",
                fg_color="transparent",
                text_color=("gray10", "gray90"),
                hover_color=("gray75", "gray30"),
                height=28,
                font=ctk.CTkFont(size=12),
                command=lambda n=name: self._select_face(n)
            )
            btn.grid(row=i, column=0, padx=2, pady=1, sticky="ew")
            self._face_buttons.append(btn)
    
    def _delete_selected_face(self):
        """Override: delete face via server API instead of locally."""
        if self._selected_face_name is None:
            self._show_message("No face selected!", "warning")
            return
        
        name = self._selected_face_name
        
        # Confirm deletion
        dialog = ctk.CTkInputDialog(
            text=f"Type '{name}' to confirm deletion:",
            title="Confirm Delete"
        )
        confirmation = dialog.get_input()
        
        if confirmation != name:
            self._show_message("Deletion cancelled.", "info")
            return
        
        success = self.server_client.delete_face(name)
        
        if success:
            self._show_message(f"🗑️ Deleted: {name}", "success")
            self._selected_face_name = None
            self._update_face_count()
        else:
            self._show_message(f"Failed to delete: {name}", "error")
    
    def _on_closing(self):
        """Override: disconnect from server on close."""
        print("[Connected] Closing application...")
        self.server_client.disconnect()
        self.is_camera_active = False
        self.destroy()
