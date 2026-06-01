# AURORA Server - Face Recognition Engine
# Ported from desktop app core/recognition.py with minimal changes

import numpy as np
from typing import Optional, List, Tuple, Dict, Any

from server import config


class FaceEngine:
    """
    Face recognition engine using InsightFace (SCRFD + ArcFace).
    Supports DirectML GPU acceleration with automatic CPU fallback.
    """

    def __init__(self):
        self.app = None
        self.active_provider = "Not Initialized"
        self.is_ready = False
        self._warmup_complete = False

    def warmup(self) -> bool:
        """
        Initialize the face analysis model with DirectML/CPU fallback.

        Returns:
            bool: True if initialization successful, False otherwise.
        """
        if self._warmup_complete:
            return self.is_ready

        from insightface.app import FaceAnalysis

        print("[FaceEngine] Starting warmup...")
        print(f"[FaceEngine] Model directory: {config.MODELS_DIR}")

        # Attempt DirectML initialization
        try:
            print(f"[FaceEngine] Attempting providers: {config.PREFERRED_PROVIDERS}")

            self.app = FaceAnalysis(
                name=config.MODEL_NAME,
                root=config.MODELS_DIR,
                providers=config.PREFERRED_PROVIDERS
            )
            self.app.prepare(ctx_id=0, det_size=config.DETECTION_SIZE)

            self.active_provider = self._detect_active_provider()
            print(f"[FaceEngine] ✓ Initialized with: {self.active_provider}")
            self.is_ready = True

        except Exception as e:
            print(f"[FaceEngine] ✗ DirectML failed: {e}")
            print("[FaceEngine] Falling back to CPU...")

            try:
                self.app = FaceAnalysis(
                    name=config.MODEL_NAME,
                    root=config.MODELS_DIR,
                    providers=config.FALLBACK_PROVIDERS
                )
                self.app.prepare(ctx_id=0, det_size=config.DETECTION_SIZE)
                self.active_provider = "CPUExecutionProvider"
                print(f"[FaceEngine] ✓ Fallback successful: {self.active_provider}")
                self.is_ready = True

            except Exception as fallback_error:
                print(f"[FaceEngine] ✗ CPU fallback also failed: {fallback_error}")
                self.active_provider = "Failed"
                self.is_ready = False

        self._warmup_complete = True

        # Run a dummy inference to pre-compile DirectML shaders + allocate GPU memory
        if self.is_ready:
            try:
                import cv2
                dummy = np.zeros((320, 320, 3), dtype=np.uint8)
                self.app.get(dummy)
                print("[FaceEngine] ✓ Warm-up inference complete (shaders compiled)")
            except Exception as e:
                print(f"[FaceEngine] ⚠ Warm-up inference failed (non-fatal): {e}")

        return self.is_ready

    def _detect_active_provider(self) -> str:
        """Detect which ONNX provider is actually being used."""
        try:
            import onnxruntime as ort
            available = ort.get_available_providers()

            if 'DmlExecutionProvider' in available:
                return "DirectML (GPU)"
            elif 'CUDAExecutionProvider' in available:
                return "CUDA (GPU)"
            else:
                return "CPUExecutionProvider"
        except Exception:
            return "Unknown"

    def detect_faces(self, frame: np.ndarray) -> List[Any]:
        """
        Detect faces in a frame.

        Args:
            frame: BGR image as numpy array

        Returns:
            List of detected face objects with bbox, landmarks, embedding, etc.
        """
        if not self.is_ready or self.app is None:
            return []

        try:
            faces = self.app.get(frame)
            return faces
        except Exception as e:
            print(f"[FaceEngine] Detection error: {e}")
            return []

    def get_embedding(self, face: Any) -> Optional[np.ndarray]:
        """
        Extract embedding vector from a detected face.

        Args:
            face: Face object from detect_faces()

        Returns:
            512-dimensional embedding vector or None
        """
        try:
            if hasattr(face, 'embedding') and face.embedding is not None:
                return face.embedding
            return None
        except Exception as e:
            print(f"[FaceEngine] Embedding error: {e}")
            return None

    def compare_faces(self, emb1: np.ndarray, emb2: np.ndarray) -> float:
        """
        Calculate cosine similarity between two face embeddings.

        Returns:
            Similarity score (0.0 to 1.0, higher = more similar)
        """
        try:
            emb1_norm = emb1 / np.linalg.norm(emb1)
            emb2_norm = emb2 / np.linalg.norm(emb2)
            similarity = np.dot(emb1_norm, emb2_norm)
            return float(similarity)
        except Exception as e:
            print(f"[FaceEngine] Comparison error: {e}")
            return 0.0

    def identify(
        self,
        embedding: np.ndarray,
        database: Dict[str, np.ndarray]
    ) -> Tuple[Optional[str], float]:
        """
        Identify a face by comparing against a database of known embeddings.

        Returns:
            Tuple of (name or None, similarity score)
        """
        if len(database) == 0:
            return None, 0.0

        best_match = None
        best_score = 0.0

        for name, stored_emb in database.items():
            score = self.compare_faces(embedding, stored_emb)
            if score > best_score:
                best_score = score
                best_match = name

        if best_score >= config.SIMILARITY_THRESHOLD:
            return best_match, best_score

        return None, best_score

    def process_frame(self, jpeg_bytes: bytes) -> List[dict]:
        """
        Process a JPEG frame and return recognition results.
        
        This is the main entry point for the server pipeline:
        JPEG bytes → decode → detect → embed → identify
        
        Args:
            jpeg_bytes: Raw JPEG image bytes
            
        Returns:
            List of dicts with keys: name, confidence, bbox
        """
        import cv2

        # Decode JPEG bytes to numpy array
        nparr = np.frombuffer(jpeg_bytes, np.uint8)
        frame = cv2.imdecode(nparr, cv2.IMREAD_COLOR)

        if frame is None:
            return []

        faces = self.detect_faces(frame)
        results = []

        for face in faces:
            embedding = self.get_embedding(face)
            if embedding is None:
                continue

            bbox = face.bbox.astype(int).tolist()
            results.append({
                "embedding": embedding,
                "bbox": bbox
            })

        return results, frame

    def get_provider_status(self) -> str:
        """Get the current active execution provider."""
        return self.active_provider
