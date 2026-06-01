# AURORA Server - Face Management API Routes

import cv2
import numpy as np
from fastapi import APIRouter, UploadFile, File, Form, HTTPException

router = APIRouter(prefix="/api", tags=["faces"])


def get_db():
    """Get database manager from app state."""
    from server.main import database
    return database


def get_engine():
    """Get face recognition engine from app state."""
    from server.main import face_engine
    return face_engine


@router.get("/faces")
async def list_faces():
    """
    List all registered faces.
    
    Returns list of name + class for each registered face.
    """
    db = get_db()
    faces = db.get_faces()
    return {"data": faces, "count": len(faces)}


@router.post("/register")
async def register_face(
    name: str = Form(..., description="Person's name"),
    face_class: str = Form("", alias="class", description="Class/section (e.g., XII-A)"),
    image: UploadFile = File(..., description="Face photo (JPEG/PNG)")
):
    """
    Register a new face.
    
    Upload a photo with a name — the server will detect faces,
    skip any that are already registered, and register the largest
    unknown face found in the image.
    """
    engine = get_engine()
    db = get_db()

    if not engine.is_ready:
        raise HTTPException(status_code=503, detail="Face engine not ready")

    # Read image
    contents = await image.read()
    nparr = np.frombuffer(contents, np.uint8)
    frame = cv2.imdecode(nparr, cv2.IMREAD_COLOR)

    if frame is None:
        raise HTTPException(status_code=400, detail="Invalid image file")

    # Detect faces (locked — DirectML not thread-safe)
    from server.main import engine_lock
    with engine_lock:
        faces = engine.detect_faces(frame)
    if len(faces) == 0:
        raise HTTPException(status_code=400, detail="No face detected in image")

    # Identify each face and find the largest UNKNOWN one
    known_embeddings = db.embeddings  # Dict[name, embedding]
    unknown_faces = []

    with engine_lock:
        for face in faces:
            embedding = engine.get_embedding(face)
            if embedding is None:
                continue

            # Check if this face is already registered
            matched_name, score = engine.identify(embedding, known_embeddings)

            if matched_name is None:
                # Unknown face — candidate for registration
                area = (face.bbox[2] - face.bbox[0]) * (face.bbox[3] - face.bbox[1])
                unknown_faces.append((face, embedding, area))

    if len(unknown_faces) == 0:
        # All detected faces are already registered
        raise HTTPException(
            status_code=400,
            detail="All faces in the image are already registered. "
                   "Make sure the person to register is in frame."
        )

    # Pick the largest unknown face (closest to camera)
    unknown_faces.sort(key=lambda x: x[2], reverse=True)
    best_face, best_embedding, _ = unknown_faces[0]

    # Register
    success = db.register_face(name, best_embedding, face_class)
    if not success:
        raise HTTPException(status_code=500, detail="Failed to save face")

    return {
        "message": f"Successfully registered {name}",
        "name": name,
        "class": face_class
    }


@router.delete("/faces/{name}")
async def delete_face(name: str):
    """
    Delete a registered face by name.
    """
    db = get_db()

    if name not in db.get_registered_names():
        raise HTTPException(status_code=404, detail=f"Face '{name}' not found")

    success = db.delete_face(name)
    if not success:
        raise HTTPException(status_code=500, detail="Failed to delete face")

    return {"message": f"Successfully deleted {name}"}
