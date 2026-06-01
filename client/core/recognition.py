# AURORA - Face Recognition Engine
# Handles face detection (SCRFD) and embedding extraction (ArcFace)

import os
import sys
import numpy as np
from typing import Optional, List, Tuple, Dict, Any

# Add parent directory to path for config import
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config


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
        
        # Try DirectML first, then fallback to CPU
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
            
            # Check which provider is actually being used
            self.active_provider = self._detect_active_provider()
            print(f"[FaceEngine] ✓ Initialized with: {self.active_provider}")
            self.is_ready = True
            
        except Exception as e:
            print(f"[FaceEngine] ✗ DirectML failed: {e}")
            print(f"[FaceEngine] Falling back to CPU...")
            
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
        
        Args:
            emb1: First embedding vector
            emb2: Second embedding vector
            
        Returns:
            Similarity score (0.0 to 1.0, higher = more similar)
        """
        try:
            # Normalize embeddings
            emb1_norm = emb1 / np.linalg.norm(emb1)
            emb2_norm = emb2 / np.linalg.norm(emb2)
            
            # Cosine similarity
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
        
        Args:
            embedding: Query embedding vector
            database: Dict mapping names to embedding vectors
            
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
        
        # Only return match if above threshold
        if best_score >= config.SIMILARITY_THRESHOLD:
            return best_match, best_score
        
        return None, best_score
    
    def get_provider_status(self) -> str:
        """Get the current active execution provider."""
        return self.active_provider
