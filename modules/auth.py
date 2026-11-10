"""Student registration and login using standard-library password hashing."""

import hashlib
import hmac
import re
import secrets
import sqlite3

from database.db import get_connection
from utils.performance import measure_function

_EMAIL_PATTERN = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")
_PBKDF2_ROUNDS = 310_000


def _hash_password(password: str, salt: bytes | None = None) -> str:
    salt = salt or secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, _PBKDF2_ROUNDS)
    return f"pbkdf2_sha256${_PBKDF2_ROUNDS}${salt.hex()}${digest.hex()}"


def _verify_password(password: str, stored_hash: str) -> bool:
    try:
        algorithm, rounds, salt_hex, digest_hex = stored_hash.split("$", 3)
        if algorithm != "pbkdf2_sha256":
            return False
        candidate = hashlib.pbkdf2_hmac(
            "sha256", password.encode("utf-8"), bytes.fromhex(salt_hex), int(rounds)
        )
        return hmac.compare_digest(candidate.hex(), digest_hex)
    except (ValueError, TypeError):
        return False


@measure_function("authentication.register_student")
def register_student(full_name: str, email: str, password: str, confirm_password: str) -> tuple[bool, str]:
    """Validate inputs and create a student; return an actionable result."""
    name = full_name.strip()
    normalized_email = email.strip().lower()
    if not name:
        return False, "Enter your full name."
    if not _EMAIL_PATTERN.fullmatch(normalized_email):
        return False, "Enter a valid email address."
    if len(password) < 8:
        return False, "Use a password with at least 8 characters."
    if password != confirm_password:
        return False, "Passwords do not match."

    connection = get_connection()
    try:
        connection.execute(
            "INSERT INTO students (display_name, email, password_hash) VALUES (?, ?, ?)",
            (name, normalized_email, _hash_password(password)),
        )
        connection.commit()
        return True, "Account created. You can now sign in."
    except sqlite3.IntegrityError:
        return False, "An account with that email already exists."
    finally:
        connection.close()


@measure_function("authentication.authenticate_student")
def authenticate_student(email: str, password: str) -> dict[str, int | str] | None:
    """Return the authenticated student's profile, or None for invalid credentials."""
    connection = get_connection()
    try:
        student = connection.execute(
            "SELECT id, display_name, email, password_hash FROM students WHERE email = ?",
            (email.strip().lower(),),
        ).fetchone()
        if not student or not student["password_hash"]:
            return None
        if not _verify_password(password, student["password_hash"]):
            return None
        return {"id": student["id"], "display_name": student["display_name"], "email": student["email"]}
    finally:
        connection.close()
