"""
One-time script to create your first admin user.
Run from the project root:

    python scripts/create_admin.py

You will be prompted for email, password, and full name.
"""

import os
import sys

# Make sure the project root is on the path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Import all models so Base.metadata knows about them
import app.models.users  # noqa: F401
from app.services.auth import create_user, get_user_by_email

from app.database import Base, SessionLocal, engine


def main():
    # Ensure the users table exists
    Base.metadata.create_all(bind=engine)

    db = SessionLocal()
    try:
        print("\n── Kubera Treasury · Create Admin User ──\n")

        email = input("Email: ").strip()
        if not email:
            print("Email cannot be empty.")
            return

        existing = get_user_by_email(db, email)
        if existing:
            print(f"User {email} already exists (role: {existing.role}).")
            return

        password = input("Password (min 8 chars): ").strip()
        if len(password) < 8:
            print("Password too short.")
            return

        full_name = input("Full name (optional): ").strip() or None

        role = input(
            "Role [system_admin / treasury_manager / treasury_analyst / auditor] (default: system_admin): "
        ).strip()
        if role not in (
            "system_admin",
            "treasury_manager",
            "treasury_analyst",
            "auditor",
        ):
            role = "system_admin"

        user = create_user(db, email, password, full_name or "", role)
        print(f"\n✓ User created: {user.email} (role: {user.role}, id: {user.id})\n")

    finally:
        db.close()


if __name__ == "__main__":
    main()
