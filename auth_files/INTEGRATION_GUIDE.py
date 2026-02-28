# AUTH INTEGRATION — HOW TO WIRE IT IN
# ======================================
# These are the ONLY changes needed in your existing files.
# Everything else is new files you copy in.

# ── 1. requirements.txt ───────────────────────────────────────────────────────
# Add these two lines:
#
#   passlib[bcrypt]==1.7.4
#   pydantic[email]
#
# Then run:  pip install passlib[bcrypt] "pydantic[email]"

# ── 2. app/main.py ────────────────────────────────────────────────────────────
# Find the section where you include routers, e.g.:
#
#   app.include_router(accounts_router)
#   app.include_router(payments_router)
#   ...
#
# Add this line alongside the others:
#
#   from app.api.v1.auth import router as auth_router
#   app.include_router(auth_router)          # <-- add this
#
# The auth router has no /api/v1 prefix by design — it lives at /auth/login
# which is what the frontend calls.

# ── 3. app/models/__init__.py (or wherever you import models) ─────────────────
# Make sure your init_db / create_all call can see the User model.
# Add this import anywhere before Base.metadata.create_all():
#
#   import app.models.users  # noqa

# ── 4. app/core/security.py — decode_token ────────────────────────────────────
# The auth router calls decode_token(token) -> dict.
# If this function doesn't exist yet, add it alongside create_access_token:
#
#   import jwt  # or jose depending on what you're using
#
#   def decode_token(token: str) -> dict:
#       return jwt.decode(token, settings.JWT_SECRET, algorithms=["HS256"])
#
# (Your existing create_access_token already signs with HS256 and JWT_SECRET
#  so this is just the inverse operation.)

# ── 5. New files to copy into your project ────────────────────────────────────
#
#   app/models/users.py          →  copy from auth_files/app/models/users.py
#   app/services/auth.py         →  copy from auth_files/app/services/auth.py
#   app/api/v1/auth.py           →  copy from auth_files/app/api/v1/auth.py
#   scripts/create_admin.py      →  copy from auth_files/scripts/create_admin.py

# ── 6. Create your first user ─────────────────────────────────────────────────
#
#   python scripts/create_admin.py
#
# Then test the endpoint:
#
#   curl -X POST http://localhost:8000/auth/login \
#     -H "Content-Type: application/json" \
#     -d '{"email":"you@company.com","password":"yourpassword"}'
#
# You should get back:  { "access_token": "eyJ...", "role": "system_admin", ... }
