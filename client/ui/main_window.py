# AURORA - Main GUI Window
# Modern CustomTkinter interface with threaded video display

import os
import sys
import queue
import time
import cv2
import numpy as np
from PIL import Image, ImageTk
from typing import Optional
import customtkinter as ctk

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config
from core.recognition import FaceEngine
from core.camera import VideoThread
from core.database import AttendanceManager


class SmartSentinelApp(ctk.CTk):  # Keep class name for compatibility
    """
    Main application window for Smart Sentinel Face Recognition System.
    Uses CustomTkinter for modern dark-mode aesthetics.
    """
    
    def __init__(self):
        super().__init__()
        
        # Configure appearance
        ctk.set_appearance_mode(config.APPEARANCE_MODE)
        ctk.set_default_color_theme(config.COLOR_THEME)
        
        # Window setup
        self.title("AURORA - Face Recognition Attendance")
        self.geometry(f"{config.WINDOW_WIDTH}x{config.WINDOW_HEIGHT}")
        self.minsize(800, 600)
        
        # Core components
        self.face_engine = FaceEngine()
        self.attendance_manager = AttendanceManager()
        self.video_thread: Optional[VideoThread] = None
        self.frame_queue = queue.Queue(maxsize=3)
        
        # State variables
        self.is_camera_active = False
        self.current_frame = None
        self.last_recognition_time = 0
        self.recognized_name = ""
        self._closest_face = None  # Closest face for registration
        
        # Build UI
        self._setup_grid()
        self._setup_sidebar()
        self._setup_video_panel()
        self._setup_status_bar()
        
        # Bind closing event
        self.protocol("WM_DELETE_WINDOW", self._on_closing)
        
        # Initialize engine in background
        self.after(100, self._initialize_engine)
    
    def _setup_grid(self):
        """Configure the main window grid layout."""
        self.grid_columnconfigure(0, weight=0)  # Sidebar (fixed)
        self.grid_columnconfigure(1, weight=1)  # Video panel (expandable)
        self.grid_rowconfigure(0, weight=1)     # Main content
        self.grid_rowconfigure(1, weight=0)     # Status bar
    
    def _setup_sidebar(self):
        """Create the left sidebar with controls."""
        self.sidebar = ctk.CTkFrame(self, width=220, corner_radius=0)
        self.sidebar.grid(row=0, column=0, rowspan=2, sticky="nsew")
        
        # Logo / Title
        self.logo_label = ctk.CTkLabel(
            self.sidebar,
            text="🌅 AURORA",
            font=ctk.CTkFont(size=20, weight="bold")
        )
        self.logo_label.grid(row=0, column=0, padx=20, pady=(20, 5))
        
        self.subtitle = ctk.CTkLabel(
            self.sidebar,
            text="Face Recognition Attendance",
            font=ctk.CTkFont(size=11),
            text_color="gray"
        )
        self.subtitle.grid(row=1, column=0, padx=20, pady=(0, 20))
        
        # Camera Controls
        self.camera_label = ctk.CTkLabel(
            self.sidebar,
            text="Camera Control",
            font=ctk.CTkFont(size=14, weight="bold")
        )
        self.camera_label.grid(row=2, column=0, padx=20, pady=(10, 5))
        
        self.start_btn = ctk.CTkButton(
            self.sidebar,
            text="▶️ Start Camera",
            command=self._start_camera,
            fg_color="#2E7D32",
            hover_color="#1B5E20"
        )
        self.start_btn.grid(row=3, column=0, padx=20, pady=5)
        
        self.stop_btn = ctk.CTkButton(
            self.sidebar,
            text="⏹️ Stop Camera",
            command=self._stop_camera,
            fg_color="#C62828",
            hover_color="#B71C1C",
            state="disabled"
        )
        self.stop_btn.grid(row=4, column=0, padx=20, pady=5)
        
        # Face Registration
        self.reg_label = ctk.CTkLabel(
            self.sidebar,
            text="Registration",
            font=ctk.CTkFont(size=14, weight="bold")
        )
        self.reg_label.grid(row=5, column=0, padx=20, pady=(20, 5))
        
        self.name_entry = ctk.CTkEntry(
            self.sidebar,
            placeholder_text="Enter name...",
            width=180
        )
        self.name_entry.grid(row=6, column=0, padx=20, pady=5)
        
        self.register_btn = ctk.CTkButton(
            self.sidebar,
            text="📸 Register Face",
            command=self._register_face,
            fg_color="#1565C0",
            hover_color="#0D47A1"
        )
        self.register_btn.grid(row=7, column=0, padx=20, pady=5)
        
        # Database Info
        self.db_label = ctk.CTkLabel(
            self.sidebar,
            text="Database",
            font=ctk.CTkFont(size=14, weight="bold")
        )
        self.db_label.grid(row=8, column=0, padx=20, pady=(20, 5))
        
        self.face_count_label = ctk.CTkLabel(
            self.sidebar,
            text="Registered: 0 faces",
            font=ctk.CTkFont(size=12)
        )
        self.face_count_label.grid(row=9, column=0, padx=20, pady=(0, 5))
        
        # Search entry
        self.search_entry = ctk.CTkEntry(
            self.sidebar,
            placeholder_text="🔍 Search faces...",
            width=180
        )
        self.search_entry.grid(row=10, column=0, padx=20, pady=(5, 2))
        self.search_entry.bind("<KeyRelease>", lambda e: self._refresh_face_list())
        
        # Registered Faces List (scrollable)
        self.face_list_frame = ctk.CTkScrollableFrame(
            self.sidebar,
            width=180,
            height=120,
            corner_radius=5
        )
        self.face_list_frame.grid(row=11, column=0, padx=20, pady=(2, 5), sticky="nsew")
        self.face_list_frame.grid_columnconfigure(0, weight=1)
        
        # Selected face tracking
        self._selected_face_name = None
        self._face_buttons = []
        
        # Delete button
        self.delete_btn = ctk.CTkButton(
            self.sidebar,
            text="🗑️ Delete Selected",
            command=self._delete_selected_face,
            fg_color="#C62828",
            hover_color="#B71C1C",
            state="disabled",
            width=180
        )
        self.delete_btn.grid(row=12, column=0, padx=20, pady=5)
        
        # Make the face list expand to fill available space
        self.sidebar.grid_rowconfigure(11, weight=1)
        
        # Appearance Mode (pushed to bottom)
        self.appearance_label = ctk.CTkLabel(
            self.sidebar,
            text="Theme:",
            font=ctk.CTkFont(size=12)
        )
        self.appearance_label.grid(row=13, column=0, padx=20, pady=(10, 0))
        
        self.appearance_menu = ctk.CTkOptionMenu(
            self.sidebar,
            values=["Dark", "Light", "System"],
            command=self._change_appearance
        )
        self.appearance_menu.grid(row=14, column=0, padx=20, pady=(5, 20))
        self.appearance_menu.set(config.APPEARANCE_MODE.capitalize())
    
    def _setup_video_panel(self):
        """Create the main video display area."""
        self.video_frame = ctk.CTkFrame(self, corner_radius=10)
        self.video_frame.grid(row=0, column=1, padx=20, pady=20, sticky="nsew")
        self.video_frame.grid_columnconfigure(0, weight=1)
        self.video_frame.grid_rowconfigure(0, weight=1)
        
        # Video display label
        self.video_label = ctk.CTkLabel(
            self.video_frame,
            text="📷 Camera Preview\n\nClick 'Start Camera' to begin",
            font=ctk.CTkFont(size=16),
            fg_color=("gray85", "gray20"),
            corner_radius=10
        )
        self.video_label.grid(row=0, column=0, padx=10, pady=10, sticky="nsew")
    
    def _setup_status_bar(self):
        """Create the bottom status bar."""
        self.status_bar = ctk.CTkFrame(self, height=40, corner_radius=0)
        self.status_bar.grid(row=1, column=1, sticky="ew", padx=20, pady=(0, 10))
        self.status_bar.grid_columnconfigure((0, 1, 2, 3), weight=1)
        
        # Provider status
        self.provider_label = ctk.CTkLabel(
            self.status_bar,
            text="Provider: Initializing...",
            font=ctk.CTkFont(size=11)
        )
        self.provider_label.grid(row=0, column=0, padx=10, pady=5)
        
        # FPS counter
        self.fps_label = ctk.CTkLabel(
            self.status_bar,
            text="FPS: --",
            font=ctk.CTkFont(size=11)
        )
        self.fps_label.grid(row=0, column=1, padx=10, pady=5)
        
        # Recognition status
        self.recognition_label = ctk.CTkLabel(
            self.status_bar,
            text="Recognition: Waiting...",
            font=ctk.CTkFont(size=11)
        )
        self.recognition_label.grid(row=0, column=2, padx=10, pady=5)
        
        # Camera status
        self.camera_status_label = ctk.CTkLabel(
            self.status_bar,
            text="Camera: Off",
            font=ctk.CTkFont(size=11)
        )
        self.camera_status_label.grid(row=0, column=3, padx=10, pady=5)
    
    def _initialize_engine(self):
        """Initialize the face recognition engine."""
        self.provider_label.configure(text="Provider: Loading models...")
        self.update_idletasks()
        
        # Warmup in main thread (blocking, but only once at startup)
        success = self.face_engine.warmup()
        
        if success:
            provider = self.face_engine.get_provider_status()
            self.provider_label.configure(text=f"Provider: {provider}")
        else:
            self.provider_label.configure(text="Provider: ❌ Failed")
        
        # Update face count
        self._update_face_count()
    
    def _start_camera(self):
        """Start the video capture thread."""
        if self.is_camera_active:
            return
        
        # Clear queue
        while not self.frame_queue.empty():
            try:
                self.frame_queue.get_nowait()
            except queue.Empty:
                break
        
        # Start video thread
        self.video_thread = VideoThread(self.frame_queue)
        self.video_thread.start()
        
        self.is_camera_active = True
        self.start_btn.configure(state="disabled")
        self.stop_btn.configure(state="normal")
        self.camera_status_label.configure(text="Camera: 🟢 Active")
        
        # Start frame update loop
        self._update_frame()
    
    def _stop_camera(self):
        """Stop the video capture thread."""
        if not self.is_camera_active:
            return
        
        self.is_camera_active = False
        
        if self.video_thread is not None:
            self.video_thread.stop()
            self.video_thread.join(timeout=2.0)
            self.video_thread = None
        
        self.start_btn.configure(state="normal")
        self.stop_btn.configure(state="disabled")
        self.camera_status_label.configure(text="Camera: ⚫ Off")
        
        # Reset video display
        self.video_label.configure(
            image=None,
            text="📷 Camera Preview\n\nClick 'Start Camera' to begin"
        )
    
    def _update_frame(self):
        """Update the video display (called via .after())."""
        if not self.is_camera_active:
            return
        
        try:
            # Get latest frame from queue
            frame_data = self.frame_queue.get_nowait()
            display_frame = frame_data['display_frame']
            detection_frame = frame_data['detection_frame']
            
            # Run face detection on smaller frame
            faces = self.face_engine.detect_faces(detection_frame)
            
            # Scale factor for bounding boxes
            scale_x = display_frame.shape[1] / detection_frame.shape[1]
            scale_y = display_frame.shape[0] / detection_frame.shape[0]
            
            # Calculate area for each face to determine closest
            faces_with_area = []
            for face in faces:
                bbox = face.bbox
                width = bbox[2] - bbox[0]
                height = bbox[3] - bbox[1]
                area = width * height
                faces_with_area.append((face, area))
            
            # First pass: identify all faces and track unknown faces
            face_info = []  # (face, area, is_known, name, score, embedding)
            for face, area in faces_with_area:
                embedding = self.face_engine.get_embedding(face)
                if embedding is not None:
                    name, score = self.face_engine.identify(
                        embedding,
                        self.attendance_manager.get_embeddings()
                    )
                    is_known = name is not None
                    face_info.append((face, area, is_known, name, score, embedding))
                else:
                    face_info.append((face, area, False, None, 0.0, None))
            
            # Find closest UNKNOWN face (largest bbox among unknowns) for registration
            unknown_faces = [(f, a, n, s, e) for f, a, k, n, s, e in face_info if not k]
            closest_unknown = None
            if unknown_faces:
                closest_unknown = max(unknown_faces, key=lambda x: x[1])[0]
            
            # Store for registration
            self._closest_face = closest_unknown
            
            # Process all faces for display
            for face, area, is_known, name, score, embedding in face_info:
                # Scale bounding box to display frame
                bbox = face.bbox.astype(int)
                x1 = int(bbox[0] * scale_x)
                y1 = int(bbox[1] * scale_y)
                x2 = int(bbox[2] * scale_x)
                y2 = int(bbox[3] * scale_y)
                
                # Is this the closest unknown face (registration candidate)?
                is_registration_candidate = (face is closest_unknown)
                
                if is_known:
                    # Known face - log attendance
                    color = config.COLOR_KNOWN
                    label = f"{name} ({score:.2f})"
                    self.recognized_name = name
                    
                    # Log attendance for ALL recognized faces
                    if self.attendance_manager.log_attendance(name):
                        self.recognition_label.configure(
                            text=f"✅ Logged: {name}"
                        )
                else:
                    # Unknown face
                    if is_registration_candidate:
                        color = config.COLOR_CLOSEST  # Cyan - registration candidate
                        label = f"[REGISTER] Unknown ({score:.2f})"
                    else:
                        color = config.COLOR_UNKNOWN  # Red - regular unknown
                        label = f"Unknown ({score:.2f})"
                    self.recognized_name = ""
                
                # Draw bounding box (thicker for registration candidate)
                thickness = 3 if is_registration_candidate else 2
                cv2.rectangle(display_frame, (x1, y1), (x2, y2), color, thickness)
                cv2.putText(
                    display_frame, label,
                    (x1, y1 - 10),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    config.FONT_SCALE,
                    color,
                    config.FONT_THICKNESS
                )
            
            # Convert to PhotoImage
            display_frame = cv2.cvtColor(display_frame, cv2.COLOR_BGR2RGB)
            
            # Resize to fit display area
            h, w = display_frame.shape[:2]
            max_w, max_h = config.VIDEO_WIDTH, config.VIDEO_HEIGHT
            
            if w > max_w or h > max_h:
                ratio = min(max_w / w, max_h / h)
                new_w, new_h = int(w * ratio), int(h * ratio)
                display_frame = cv2.resize(display_frame, (new_w, new_h))
            
            image = Image.fromarray(display_frame)
            photo = ctk.CTkImage(light_image=image, dark_image=image, size=(image.width, image.height))
            
            self.video_label.configure(image=photo, text="")
            self.video_label.image = photo  # Keep reference
            
            # Update FPS
            if self.video_thread is not None:
                fps = self.video_thread.get_fps()
                self.fps_label.configure(text=f"FPS: {fps:.1f}")
            
        except queue.Empty:
            pass
        except Exception as e:
            print(f"[GUI] Frame update error: {e}")
        
        # Schedule next update
        if self.is_camera_active:
            self.after(config.FRAME_UPDATE_MS, self._update_frame)
    
    def _register_face(self):
        """Register the closest UNKNOWN face from current frame."""
        name = self.name_entry.get().strip()
        
        if not name:
            self._show_message("Please enter a name first!", "warning")
            return
        
        if not self.is_camera_active:
            self._show_message("Please start the camera first!", "warning")
            return
        
        # Get current frame from queue
        try:
            frame_data = self.frame_queue.get_nowait()
            detection_frame = frame_data['detection_frame']
        except queue.Empty:
            self._show_message("No frame available. Try again.", "warning")
            return
        
        # Detect faces
        faces = self.face_engine.detect_faces(detection_frame)
        
        if len(faces) == 0:
            self._show_message("No face detected. Position your face in view.", "warning")
            return
        
        # Calculate area and identify each face
        unknown_faces = []  # (face, area, embedding)
        for face in faces:
            bbox = face.bbox
            width = bbox[2] - bbox[0]
            height = bbox[3] - bbox[1]
            area = width * height
            
            embedding = self.face_engine.get_embedding(face)
            if embedding is not None:
                # Check if this face is already registered
                existing_name, score = self.face_engine.identify(
                    embedding,
                    self.attendance_manager.get_embeddings()
                )
                
                if existing_name is None:
                    # This is an unknown face - can be registered
                    unknown_faces.append((face, area, embedding))
        
        if len(unknown_faces) == 0:
            self._show_message("All faces are already registered!", "warning")
            return
        
        # Select the closest unknown face (largest bounding box)
        closest_unknown = max(unknown_faces, key=lambda x: x[1])
        embedding = closest_unknown[2]
        
        # Register
        success = self.attendance_manager.register_face(name, embedding)
        
        if success:
            total_faces = len(faces)
            msg = f"✅ Registered: {name}"
            if total_faces > 1:
                msg += f" (closest of {len(unknown_faces)} unknown)"
            self._show_message(msg, "success")
            self.name_entry.delete(0, 'end')
            self._update_face_count()
        else:
            self._show_message("Failed to register face.", "error")
    
    def _update_face_count(self):
        """Update the registered face count display and refresh face list."""
        count = self.attendance_manager.get_face_count()
        self.face_count_label.configure(text=f"Registered: {count} faces")
        self._refresh_face_list()
    
    def _refresh_face_list(self):
        """Populate the scrollable face list with registered names."""
        # Clear existing buttons
        for btn in self._face_buttons:
            btn.destroy()
        self._face_buttons.clear()
        self._selected_face_name = None
        self.delete_btn.configure(state="disabled")
        
        # Get registered names, filter by search, sort alphabetically
        search_query = self.search_entry.get().strip().lower()
        names = sorted(self.attendance_manager.get_registered_names())
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
    
    def _select_face(self, name: str):
        """Handle clicking a face in the list."""
        self._selected_face_name = name
        self.delete_btn.configure(state="normal")
        
        # Highlight selected, reset others
        for btn in self._face_buttons:
            btn_name = btn.cget("text").replace("👤 ", "")
            if btn_name == name:
                btn.configure(fg_color=("#3B8ED0", "#1F6AA5"))
            else:
                btn.configure(fg_color="transparent")
        
        self._show_message(f"Selected: {name}", "info")
    
    def _delete_selected_face(self):
        """Delete the selected face from the database."""
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
        
        success = self.attendance_manager.delete_face(name)
        
        if success:
            self._show_message(f"🗑️ Deleted: {name}", "success")
            self._selected_face_name = None
            self._update_face_count()
        else:
            self._show_message(f"Failed to delete: {name}", "error")
    
    def _change_appearance(self, mode: str):
        """Change the application appearance mode."""
        ctk.set_appearance_mode(mode.lower())
    
    def _show_message(self, message: str, msg_type: str = "info"):
        """Show a temporary message in the recognition label."""
        color = {
            "success": "#4CAF50",
            "warning": "#FF9800",
            "error": "#F44336",
            "info": None
        }.get(msg_type)
        
        self.recognition_label.configure(text=message)
        
        # Reset after 3 seconds
        self.after(3000, lambda: self.recognition_label.configure(
            text="Recognition: Waiting..."
        ))
    
    def _on_closing(self):
        """Handle window close event."""
        print("[GUI] Closing application...")
        self._stop_camera()
        self.destroy()


if __name__ == "__main__":
    app = SmartSentinelApp()
    app.mainloop()
