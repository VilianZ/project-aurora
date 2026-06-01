# AURORA Server - Attendance API Routes

from fastapi import APIRouter, Query
from typing import Optional

router = APIRouter(prefix="/api", tags=["attendance"])


def get_db():
    """Get database manager from app state."""
    from server.main import database
    return database


@router.get("/attendance")
async def get_attendance(
    date: Optional[str] = Query(None, description="Filter by date (YYYY-MM-DD)"),
    class_filter: Optional[str] = Query(None, alias="class", description="Filter by class"),
    search: Optional[str] = Query(None, description="Search by name"),
):
    """
    Get attendance records with optional filters.
    
    Returns list of attendance records, most recent first.
    """
    db = get_db()
    records = db.get_attendance(
        date_filter=date,
        class_filter=class_filter,
        search=search
    )
    return {"data": records, "count": len(records)}


@router.get("/stats")
async def get_stats():
    """
    Get today's attendance statistics.
    
    Returns: total_registered, present, late, absent counts.
    """
    db = get_db()
    stats = db.get_stats()
    return stats
