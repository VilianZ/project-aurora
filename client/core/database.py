# AURORA - Attendance Database Manager
# Handles face embedding storage and CSV attendance logging

import os
import sys
import csv
import time
import numpy as np
from datetime import datetime, date
from typing import Dict, Optional, List, Tuple

# Add parent directory to path for config import
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config


class AttendanceManager:
    """
    Manages face embeddings database and attendance CSV logging.
    Implements persistent daily cache to prevent duplicate logs.
    """
    
    def __init__(
        self,
        faces_dir: str = config.FACES_DIR,
        csv_path: str = config.ATTENDANCE_CSV
    ):
        """
        Initialize the attendance manager.
        
        Args:
            faces_dir: Directory for storing face embeddings (.npy files)
            csv_path: Path to the attendance CSV log
        """
        self.faces_dir = faces_dir
        self.csv_path = csv_path
        
        # In-memory cache of embeddings
        self._embeddings: Dict[str, np.ndarray] = {}
        
        # Cooldown tracking: {name: last_logged_timestamp} (short-term anti-spam)
        self._last_logged: Dict[str, float] = {}
        
        # Daily attendance cache: set of names already logged TODAY
        # This persists by loading from CSV on startup
        self._today_logged: set = set()
        self._cache_date: str = ""  # Track current date for cache invalidation
        
        # Ensure directories exist
        os.makedirs(self.faces_dir, exist_ok=True)
        os.makedirs(os.path.dirname(self.csv_path), exist_ok=True)
        
        # Initialize CSV if it doesn't exist
        self._init_csv()
        
        # Load existing embeddings
        self.load_faces()
        
        # Load today's attendance from CSV (persistent cache)
        self._load_today_cache()
    
    def _init_csv(self):
        """Initialize CSV file with headers if it doesn't exist."""
        if not os.path.exists(self.csv_path):
            with open(self.csv_path, 'w', newline='', encoding='utf-8') as f:
                writer = csv.writer(f)
                writer.writerow(['Name', 'Date', 'Time', 'Timestamp'])
            print(f"[AttendanceManager] Created attendance log: {self.csv_path}")
    
    def _load_today_cache(self):
        """
        Load today's already-logged names from CSV into memory.
        This ensures persistence across app restarts.
        """
        today = date.today().strftime("%Y-%m-%d")
        self._cache_date = today
        self._today_logged.clear()
        
        if not os.path.exists(self.csv_path):
            return
        
        try:
            with open(self.csv_path, 'r', encoding='utf-8') as f:
                reader = csv.reader(f)
                next(reader, None)  # Skip header
                
                for row in reader:
                    if len(row) >= 2 and row[1] == today:
                        self._today_logged.add(row[0])  # Add name to cache
            
            if self._today_logged:
                print(f"[AttendanceManager] ✓ Loaded {len(self._today_logged)} names already logged today: {self._today_logged}")
            else:
                print(f"[AttendanceManager] No attendance logged yet for {today}")
                
        except Exception as e:
            print(f"[AttendanceManager] Failed to load today's cache: {e}")
    
    def load_faces(self) -> int:
        """
        Load all face embeddings from the faces directory.
        
        Returns:
            Number of faces loaded
        """
        self._embeddings.clear()
        
        if not os.path.exists(self.faces_dir):
            return 0
        
        for filename in os.listdir(self.faces_dir):
            if filename.endswith('.npy'):
                name = filename[:-4]  # Remove .npy extension
                filepath = os.path.join(self.faces_dir, filename)
                
                try:
                    embedding = np.load(filepath)
                    self._embeddings[name] = embedding
                    print(f"[AttendanceManager] Loaded: {name}")
                except Exception as e:
                    print(f"[AttendanceManager] Failed to load {filename}: {e}")
        
        print(f"[AttendanceManager] ✓ Loaded {len(self._embeddings)} faces")
        return len(self._embeddings)
    
    def register_face(self, name: str, embedding: np.ndarray) -> bool:
        """
        Save a new face embedding to the database.
        
        Args:
            name: Person's name (will be used as filename)
            embedding: 512-dimensional face embedding
            
        Returns:
            True if saved successfully, False otherwise
        """
        if name is None or len(name.strip()) == 0:
            print("[AttendanceManager] Invalid name")
            return False
        
        if embedding is None or len(embedding) == 0:
            print("[AttendanceManager] Invalid embedding")
            return False
        
        # Sanitize name for filename
        safe_name = "".join(c for c in name if c.isalnum() or c in (' ', '-', '_')).strip()
        if len(safe_name) == 0:
            print("[AttendanceManager] Name contains no valid characters")
            return False
        
        filepath = os.path.join(self.faces_dir, f"{safe_name}.npy")
        
        try:
            np.save(filepath, embedding)
            self._embeddings[safe_name] = embedding
            print(f"[AttendanceManager] ✓ Registered: {safe_name}")
            return True
        except Exception as e:
            print(f"[AttendanceManager] Failed to save {safe_name}: {e}")
            return False
    
    def delete_face(self, name: str) -> bool:
        """
        Delete a face from the database.
        
        Args:
            name: Person's name
            
        Returns:
            True if deleted successfully, False otherwise
        """
        filepath = os.path.join(self.faces_dir, f"{name}.npy")
        
        try:
            if os.path.exists(filepath):
                os.remove(filepath)
            if name in self._embeddings:
                del self._embeddings[name]
            print(f"[AttendanceManager] ✓ Deleted: {name}")
            return True
        except Exception as e:
            print(f"[AttendanceManager] Failed to delete {name}: {e}")
            return False
    
    def log_attendance(self, name: str) -> bool:
        """
        Log attendance for a person (with daily duplicate prevention).
        
        Args:
            name: Person's name
            
        Returns:
            True if logged, False if already logged today or within cooldown
        """
        current_time = time.time()
        today = date.today().strftime("%Y-%m-%d")
        
        # Check if day has changed (midnight rollover)
        if self._cache_date != today:
            print(f"[AttendanceManager] New day detected, refreshing cache...")
            self._load_today_cache()
        
        # Check if already logged TODAY (persistent across restarts)
        if name in self._today_logged:
            # Still apply short cooldown to avoid spamming "already logged" messages
            if name in self._last_logged:
                elapsed = current_time - self._last_logged[name]
                if elapsed < config.ATTENDANCE_COOLDOWN:
                    return False  # Silently skip
            self._last_logged[name] = current_time
            return False  # Already logged today
        
        # Short-term cooldown (anti-spam for rapid detections)
        if name in self._last_logged:
            elapsed = current_time - self._last_logged[name]
            if elapsed < config.ATTENDANCE_COOLDOWN:
                return False  # Still in cooldown
        
        # Log attendance
        now = datetime.now()
        date_str = now.strftime("%Y-%m-%d")
        time_str = now.strftime("%H:%M:%S")
        
        try:
            with open(self.csv_path, 'a', newline='', encoding='utf-8') as f:
                writer = csv.writer(f)
                writer.writerow([name, date_str, time_str, current_time])
            
            # Update both caches
            self._last_logged[name] = current_time
            self._today_logged.add(name)  # Add to daily cache
            
            print(f"[AttendanceManager] ✓ Logged attendance: {name} at {time_str}")
            return True
            
        except Exception as e:
            print(f"[AttendanceManager] Failed to log {name}: {e}")
            return False
    
    def get_today_log(self) -> List[Tuple[str, str]]:
        """
        Get today's attendance records.
        
        Returns:
            List of (name, time) tuples for today
        """
        today = date.today().strftime("%Y-%m-%d")
        records = []
        
        try:
            with open(self.csv_path, 'r', encoding='utf-8') as f:
                reader = csv.reader(f)
                next(reader)  # Skip header
                
                for row in reader:
                    if len(row) >= 3 and row[1] == today:
                        records.append((row[0], row[2]))  # (name, time)
                        
        except Exception as e:
            print(f"[AttendanceManager] Failed to read log: {e}")
        
        return records
    
    def get_embeddings(self) -> Dict[str, np.ndarray]:
        """Get all loaded embeddings."""
        return self._embeddings
    
    def get_registered_names(self) -> List[str]:
        """Get list of registered names."""
        return list(self._embeddings.keys())
    
    def get_face_count(self) -> int:
        """Get number of registered faces."""
        return len(self._embeddings)
