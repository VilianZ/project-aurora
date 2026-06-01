# AURORA Server - Database Manager
# Dual-write: Supabase (cloud) + CSV (local failsafe)

import sys
if sys.stdout.encoding != 'utf-8':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

import os
import csv
import time
import numpy as np
from datetime import datetime, date
from typing import Dict, Optional, List, Tuple
from collections import deque

from server import config


class DatabaseManager:
    """
    Manages face embeddings (.npy files), Supabase cloud database,
    and local CSV attendance logging with dual-write failsafe.
    """

    def __init__(self):
        self.embeddings: Dict[str, np.ndarray] = {}
        self.face_classes: Dict[str, str] = {}  # name -> class
        self._today_logged: set = set()
        self._last_log_time: Dict[str, float] = {}
        self._pending_queue: deque = deque(maxlen=1000)

        # Supabase client (initialized lazily)
        self._supabase = None

        # Initialize
        self._init_csv()
        self._load_today_cache()
        self.load_faces()

    # =========================================================================
    # SUPABASE
    # =========================================================================

    def _get_supabase(self):
        """Lazy-initialize Supabase client."""
        if not config.SUPABASE_URL or not config.SUPABASE_KEY:
            return None

        if self._supabase is None:
            try:
                from supabase import create_client
                self._supabase = create_client(
                    config.SUPABASE_URL,
                    config.SUPABASE_KEY
                )
                print("[Database] ✓ Supabase client initialized")
            except Exception as e:
                print(f"[Database] ✗ Supabase init failed: {e}")
                self._supabase = None
        return self._supabase

    def _sync_pending(self):
        """Retry any queued Supabase writes."""
        if not self._pending_queue:
            return

        sb = self._get_supabase()
        if sb is None:
            return

        retried = 0
        while self._pending_queue:
            record = self._pending_queue[0]
            try:
                sb.table("attendance").insert(record).execute()
                self._pending_queue.popleft()
                retried += 1
            except Exception:
                break  # Stop on first failure

        if retried > 0:
            print(f"[Database] ✓ Synced {retried} pending records to Supabase")

    # =========================================================================
    # CSV (LOCAL FAILSAFE)
    # =========================================================================

    def _init_csv(self):
        """Initialize CSV file with headers if it doesn't exist."""
        if not os.path.exists(config.ATTENDANCE_CSV):
            with open(config.ATTENDANCE_CSV, 'w', newline='') as f:
                writer = csv.writer(f)
                writer.writerow(['name', 'class', 'date', 'time', 'status', 'confidence'])
            print(f"[Database] ✓ Created CSV: {config.ATTENDANCE_CSV}")

    def _load_today_cache(self):
        """Load today's already-logged names from CSV into memory."""
        today = date.today().isoformat()
        self._today_logged.clear()

        if not os.path.exists(config.ATTENDANCE_CSV):
            return

        try:
            with open(config.ATTENDANCE_CSV, 'r') as f:
                reader = csv.DictReader(f)
                for row in reader:
                    if row.get('date') == today:
                        self._today_logged.add(row['name'])
        except Exception as e:
            print(f"[Database] Warning: Could not load today cache: {e}")

    # =========================================================================
    # FACE EMBEDDINGS (.npy)
    # =========================================================================

    def _classes_json_path(self) -> str:
        """Path to the local face_classes.json file."""
        return os.path.join(config.FACES_DIR, "face_classes.json")

    def _save_classes_json(self):
        """Persist face_classes dict to a local JSON file."""
        try:
            import json
            with open(self._classes_json_path(), 'w') as f:
                json.dump(self.face_classes, f, indent=2)
        except Exception as e:
            print(f"[Database] Warning: Could not save face_classes.json: {e}")

    def load_faces(self) -> int:
        """
        Load all face embeddings from the faces directory
        and rebuild face_classes from local JSON, Supabase, then CSV.

        Returns:
            Number of faces loaded
        """
        self.embeddings.clear()
        self.face_classes.clear()

        if not os.path.exists(config.FACES_DIR):
            return 0

        count = 0
        for filename in os.listdir(config.FACES_DIR):
            if filename.endswith('.npy'):
                name = os.path.splitext(filename)[0]
                filepath = os.path.join(config.FACES_DIR, filename)
                try:
                    embedding = np.load(filepath)
                    self.embeddings[name] = embedding
                    count += 1
                except Exception as e:
                    print(f"[Database] Warning: Could not load {filename}: {e}")

        # Source 1: Local face_classes.json (fastest, always available)
        json_path = self._classes_json_path()
        if os.path.exists(json_path):
            try:
                import json
                with open(json_path, 'r') as f:
                    saved = json.load(f)
                for name, fc in saved.items():
                    if name in self.embeddings:
                        self.face_classes[name] = fc
                print(f"[Database] ✓ Loaded {len(self.face_classes)} face classes from local JSON")
            except Exception as e:
                print(f"[Database] Warning: Could not load face_classes.json: {e}")

        # Source 2: Supabase (fills any gaps)
        missing = [n for n in self.embeddings if n not in self.face_classes]
        if missing:
            sb = self._get_supabase()
            if sb:
                try:
                    resp = sb.table("faces").select("name, class").execute()
                    for row in (resp.data or []):
                        name = row.get("name", "")
                        face_class = row.get("class", "")
                        if name in self.embeddings and name not in self.face_classes:
                            self.face_classes[name] = face_class
                except Exception as e:
                    print(f"[Database] Warning: Could not load face classes from Supabase: {e}")

        # Source 3: CSV attendance records (last resort)
        missing = [n for n in self.embeddings if n not in self.face_classes]
        if missing and os.path.exists(config.ATTENDANCE_CSV):
            try:
                with open(config.ATTENDANCE_CSV, 'r') as f:
                    reader = csv.DictReader(f)
                    for row in reader:
                        name = row.get('name', '')
                        face_class = row.get('class', '')
                        if name in self.embeddings and name not in self.face_classes and face_class:
                            self.face_classes[name] = face_class
            except Exception as e:
                print(f"[Database] Warning: Could not load face classes from CSV: {e}")

        # Persist whatever we've recovered so next restart is instant
        if self.face_classes:
            self._save_classes_json()

        print(f"[Database] ✓ Loaded {count} face embeddings, {len(self.face_classes)} with class info")
        return count

    def register_face(self, name: str, embedding: np.ndarray, face_class: str = "") -> bool:
        """
        Save a new face embedding to the database.

        Args:
            name: Person's name
            embedding: 512-dimensional face embedding
            face_class: Class/section (e.g., "XII-A")

        Returns:
            True if saved successfully
        """
        try:
            # Save .npy file
            filepath = os.path.join(config.FACES_DIR, f"{name}.npy")
            np.save(filepath, embedding)
            self.embeddings[name] = embedding
            self.face_classes[name] = face_class
            self._save_classes_json()  # Persist locally

            # Save to Supabase
            sb = self._get_supabase()
            if sb:
                try:
                    sb.table("faces").upsert({
                        "name": name,
                        "class": face_class
                    }).execute()
                except Exception as e:
                    print(f"[Database] Warning: Supabase face save failed: {e}")

            print(f"[Database] ✓ Registered face: {name}")
            return True

        except Exception as e:
            print(f"[Database] ✗ Failed to register {name}: {e}")
            return False

    def delete_face(self, name: str) -> bool:
        """
        Delete a face from the database.

        Args:
            name: Person's name

        Returns:
            True if deleted successfully
        """
        try:
            # Delete .npy file
            filepath = os.path.join(config.FACES_DIR, f"{name}.npy")
            if os.path.exists(filepath):
                os.remove(filepath)

            # Remove from memory
            self.embeddings.pop(name, None)
            self.face_classes.pop(name, None)
            self._save_classes_json()  # Keep local JSON in sync

            # Delete from Supabase
            sb = self._get_supabase()
            if sb:
                try:
                    sb.table("faces").delete().eq("name", name).execute()
                except Exception as e:
                    print(f"[Database] Warning: Supabase face delete failed: {e}")

            print(f"[Database] ✓ Deleted face: {name}")
            return True

        except Exception as e:
            print(f"[Database] ✗ Failed to delete {name}: {e}")
            return False

    # =========================================================================
    # ATTENDANCE LOGGING (DUAL-WRITE)
    # =========================================================================

    def log_attendance(
        self, name: str, confidence: float = 0.0, face_class: str = ""
    ) -> bool:
        """
        Log attendance with dual-write (Supabase + CSV).
        Includes daily duplicate prevention and cooldown.

        Args:
            name: Person's name
            confidence: Recognition confidence score

        Returns:
            The attendance status string ("present" or "late") if logged,
            or False if already logged or within cooldown.
        """
        now = datetime.now()
        today = now.date().isoformat()
        current_time = now.strftime("%H:%M:%S")

        # Check daily duplicate
        if name in self._today_logged:
            return False

        # Check cooldown
        last_time = self._last_log_time.get(name, 0)
        if time.time() - last_time < config.ATTENDANCE_COOLDOWN:
            return False

        # Determine status
        hour = now.hour
        if hour < 7:
            status = "present"  # Before 7 AM = early/present
        elif hour < 8:
            status = "present"  # 7-8 AM = on time
        else:
            status = "late"     # After 8 AM = late

        # === WRITE 1: CSV (always succeeds) ===
        try:
            with open(config.ATTENDANCE_CSV, 'a', newline='') as f:
                writer = csv.writer(f)
                writer.writerow([name, face_class, today, current_time, status, f"{confidence:.2f}"])
        except Exception as e:
            print(f"[Database] ✗ CSV write failed: {e}")

        # === WRITE 2: Supabase (may fail, queue if so) ===
        record = {
            "name": name,
            "class": face_class,
            "date": today,
            "time": current_time,
            "status": status,
            "confidence": round(confidence, 4)
        }

        sb = self._get_supabase()
        if sb:
            try:
                sb.table("attendance").insert(record).execute()
            except Exception as e:
                print(f"[Database] Warning: Supabase write failed, queuing: {e}")
                self._pending_queue.append(record)
        else:
            self._pending_queue.append(record)

        # Update caches
        self._today_logged.add(name)
        self._last_log_time[name] = time.time()

        print(f"[Database] ✓ Logged attendance: {name} ({status}) @ {current_time}")

        # Try to sync any pending records
        self._sync_pending()

        return status  # Return actual status ("present" or "late")

    # =========================================================================
    # ACTIVITY LOGGING (activity_logs table)
    # =========================================================================

    def log_activity(
        self,
        event_type: str,
        name: str = None,
        confidence: float = None,
        face_class: str = None,
        details: str = None
    ) -> bool:
        """
        Log a detection/activity event to the activity_logs table.

        Args:
            event_type: 'KNOWN', 'UNKNOWN', or 'ATTENDANCE'
            name: Person's name (None for unknowns)
            confidence: Recognition confidence score
            face_class: Person's class (None for unknowns)
            details: Extra info/description

        Returns:
            True if written successfully
        """
        record = {
            "event_type": event_type,
            "name": name,
            "face_class": face_class,
            "confidence": round(confidence, 4) if confidence else None,
            "details": details
        }

        sb = self._get_supabase()
        if sb:
            try:
                sb.table("activity_logs").insert(record).execute()
                return True
            except Exception as e:
                print(f"[Database] Warning: activity_logs write failed: {e}")
                return False
        return False

    # =========================================================================
    # QUERIES
    # =========================================================================

    def get_attendance(
        self, 
        date_filter: str = None, 
        class_filter: str = None,
        search: str = None
    ) -> List[dict]:
        """
        Get attendance records from Supabase with optional filters.
        Falls back to CSV on failure.
        """
        sb = self._get_supabase()
        if sb:
            try:
                query = sb.table("attendance").select("*")

                if date_filter:
                    query = query.eq("date", date_filter)
                if class_filter:
                    query = query.eq("class", class_filter)
                if search:
                    query = query.ilike("name", f"%{search}%")

                query = query.order("created_at", desc=True)
                response = query.execute()
                return response.data

            except Exception as e:
                print(f"[Database] Supabase query failed, falling back to CSV: {e}")

        # Fallback: read from CSV
        return self._get_attendance_csv(date_filter, class_filter, search)

    def _get_attendance_csv(
        self, date_filter=None, class_filter=None, search=None
    ) -> List[dict]:
        """Read attendance from local CSV as fallback."""
        records = []

        if not os.path.exists(config.ATTENDANCE_CSV):
            return records

        try:
            with open(config.ATTENDANCE_CSV, 'r') as f:
                reader = csv.DictReader(f)
                for row in reader:
                    if date_filter and row.get('date') != date_filter:
                        continue
                    if class_filter and row.get('class') != class_filter:
                        continue
                    if search and search.lower() not in row.get('name', '').lower():
                        continue
                    records.append(row)
        except Exception as e:
            print(f"[Database] CSV read failed: {e}")

        records.reverse()  # Most recent first
        return records

    def get_faces(self) -> List[dict]:
        """Get list of all registered faces."""
        faces = []
        for name in sorted(self.embeddings.keys()):
            faces.append({
                "name": name,
                "class": self.face_classes.get(name, ""),
                "has_embedding": True
            })
        return faces

    def get_stats(self) -> dict:
        """Get today's attendance statistics."""
        today = date.today().isoformat()
        records = self.get_attendance(date_filter=today)

        total_registered = len(self.embeddings)
        present = sum(1 for r in records if r.get('status') in ('present',))
        late = sum(1 for r in records if r.get('status') == 'late')
        absent = total_registered - present - late

        return {
            "total_registered": total_registered,
            "present": present,
            "late": late,
            "absent": max(0, absent),
            "date": today
        }

    def get_embeddings(self) -> Dict[str, np.ndarray]:
        """Get all loaded embeddings."""
        return self.embeddings

    def get_registered_names(self) -> List[str]:
        """Get list of registered names."""
        return list(self.embeddings.keys())

    def get_face_count(self) -> int:
        """Get number of registered faces."""
        return len(self.embeddings)
