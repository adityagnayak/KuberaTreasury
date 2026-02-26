#!/usr/bin/env python3
"""
Initialize the NexusTreasury database.
Creates all tables and installs SQLite triggers (if using SQLite).
"""

import sys
from pathlib import Path

# Allow running from project root
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.database import init_db, engine
from app.config import settings

def main():
    print(f"Initializing database...")
    print(f"  DATABASE_URL: {settings.DATABASE_URL[:40]}...")
    print(f"  Environment: {settings.ENVIRONMENT}")

    init_db()

    print("Database initialized successfully.")
    print("All tables created.")
    if settings.is_sqlite:
        print("SQLite triggers installed (audit immutability, shadow archive).")

if __name__ == "__main__":
    main()
