"""
Thin wrappers around the bcrypt package for hashing and verifying passwords.

Replaces passlib.hash.bcrypt — passlib 1.7.4 is incompatible with bcrypt ≥ 4.0
(it tries to read bcrypt.__about__.__version__ which no longer exists).
The raw bcrypt package produces identical $2b$ hashes so all existing stored
hashes continue to verify without any migration.
"""
import bcrypt as _bcrypt


def hash_password(password: str) -> str:
    return _bcrypt.hashpw(password.encode(), _bcrypt.gensalt()).decode()


def verify_password(password: str, hashed: str) -> bool:
    try:
        return _bcrypt.checkpw(password.encode(), hashed.encode())
    except Exception:
        return False
