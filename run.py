"""Top-level entry point (used by PyInstaller and direct `python run.py`)."""
import sys
import os

# Ensure project root is on the path when run directly
sys.path.insert(0, os.path.dirname(__file__))

from backend.main import main

if __name__ == "__main__":
    main()
