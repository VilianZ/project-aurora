# Core module for Smart Sentinel
from .recognition import FaceEngine
from .camera import VideoThread
from .database import AttendanceManager

__all__ = ['FaceEngine', 'VideoThread', 'AttendanceManager']
