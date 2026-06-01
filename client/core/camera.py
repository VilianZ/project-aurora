# AURORA - Video Capture Thread
# Handles continuous frame capture in a background thread

import os
import sys
import cv2
import threading
import queue
import time
from typing import Optional, Tuple

# Add parent directory to path for config import
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config


class VideoThread(threading.Thread):
    """
    Background thread for continuous video capture.
    Frames are placed in a queue for the main GUI thread to consume.
    """
    
    def __init__(
        self,
        frame_queue: queue.Queue,
        camera_id: int = config.CAMERA_ID,
        resolution: Tuple[int, int] = (config.CAMERA_WIDTH, config.CAMERA_HEIGHT)
    ):
        """
        Initialize the video capture thread.
        
        Args:
            frame_queue: Queue to put captured frames
            camera_id: Camera device ID (default: 0)
            resolution: Tuple of (width, height) for capture
        """
        super().__init__(daemon=True)
        
        self.frame_queue = frame_queue
        self.camera_id = camera_id
        self.resolution = resolution
        
        self._stop_event = threading.Event()
        self._cap: Optional[cv2.VideoCapture] = None
        
        self.fps = 0.0
        self.is_running = False
        self.last_error = None
    
    def run(self):
        """Main thread loop - captures frames continuously."""
        print(f"[VideoThread] Starting capture on camera {self.camera_id}")
        
        # Initialize camera
        try:
            self._cap = cv2.VideoCapture(self.camera_id, cv2.CAP_DSHOW)  # DirectShow for Windows
            
            if not self._cap.isOpened():
                self.last_error = f"Failed to open camera {self.camera_id}"
                print(f"[VideoThread] ✗ {self.last_error}")
                return
            
            # Set resolution
            self._cap.set(cv2.CAP_PROP_FRAME_WIDTH, self.resolution[0])
            self._cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.resolution[1])
            
            # Set buffer size to minimize latency
            self._cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
            
            print(f"[VideoThread] ✓ Camera opened at {self.resolution[0]}x{self.resolution[1]}")
            self.is_running = True
            
        except Exception as e:
            self.last_error = str(e)
            print(f"[VideoThread] ✗ Camera init error: {e}")
            return
        
        # FPS calculation
        frame_count = 0
        fps_start_time = time.time()
        
        # Main capture loop
        while not self._stop_event.is_set():
            try:
                ret, frame = self._cap.read()
                
                if not ret or frame is None:
                    # Skip bad frames but continue trying
                    time.sleep(0.01)
                    continue
                
                # Create detection frame (downscaled)
                detection_frame = cv2.resize(
                    frame,
                    (config.DETECTION_WIDTH, config.DETECTION_HEIGHT),
                    interpolation=cv2.INTER_LINEAR
                )
                
                # Put frame data in queue (replace old frames if queue is full)
                frame_data = {
                    'display_frame': frame,
                    'detection_frame': detection_frame,
                    'timestamp': time.time()
                }
                
                try:
                    # Non-blocking put - if queue is full, discard oldest
                    if self.frame_queue.full():
                        try:
                            self.frame_queue.get_nowait()
                        except queue.Empty:
                            pass
                    self.frame_queue.put_nowait(frame_data)
                except queue.Full:
                    pass
                
                # Calculate FPS
                frame_count += 1
                elapsed = time.time() - fps_start_time
                if elapsed >= 1.0:
                    self.fps = frame_count / elapsed
                    frame_count = 0
                    fps_start_time = time.time()
                    
            except Exception as e:
                print(f"[VideoThread] Frame capture error: {e}")
                time.sleep(0.01)
        
        # Cleanup
        self._cleanup()
    
    def stop(self):
        """Signal the thread to stop and wait for cleanup."""
        print("[VideoThread] Stop requested")
        self._stop_event.set()
        self.is_running = False
    
    def _cleanup(self):
        """Release camera resources."""
        if self._cap is not None:
            self._cap.release()
            self._cap = None
        print("[VideoThread] ✓ Camera released")
    
    def get_fps(self) -> float:
        """Get current frames per second."""
        return self.fps
    
    def is_camera_open(self) -> bool:
        """Check if camera is currently open."""
        return self._cap is not None and self._cap.isOpened()
