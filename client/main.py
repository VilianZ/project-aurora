#!/usr/bin/env python3
"""
AURORA - Client Viewer
Connect to an AURORA server to view the live feed.

Usage:
    python main.py                            # Connect to localhost
    python main.py --url=http://192.168.1.5:8000  # Connect to specific server
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def main():
    print("=" * 50)
    print("  AURORA - Client Viewer")
    print("=" * 50)
    print()

    # Check dependencies
    try:
        import cv2
        import numpy as np
        import customtkinter
        from PIL import Image
        import websockets
        print("All dependencies OK")
    except ImportError as e:
        print(f"Missing dependency: {e}")
        print("\nInstall with:")
        print("  pip install -r requirements.txt")
        sys.exit(1)

    # Determine server URL
    server_url = "http://127.0.0.1:8000"
    for arg in sys.argv:
        if arg.startswith("--url="):
            server_url = arg.split("=", 1)[1]

    print(f"Server: {server_url}")
    print()

    from ui.connected_window import ConnectedSentinelApp
    app = ConnectedSentinelApp(server_url=server_url)
    app.mainloop()


if __name__ == "__main__":
    main()
