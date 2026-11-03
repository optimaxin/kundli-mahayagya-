"""Cryptographic primitives: password hashing, JWT, QR tokens, data encryption."""

from __future__ import annotations

import hashlib
import hmac
import secrets
import uuid
from datetime import datetime, timedelta
from typing import Any

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError
from cryptography.fernet import Fernet, InvalidToken

from app.core import clock
from app.core.config import get_settings

# --------------------------------------------------------------- passwords
_hasher = PasswordHasher()  # Argon2id with library-recommended parameters
# Used to equalise timing when the user does not exist.
_DUMMY_HASH = _hasher.hash(secrets.token_urlsafe(16))


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password: str, password_hash: str | None) -> bool:
    try:
        return _hasher.verify(password_hash or _DUMMY_HASH, password) and password_hash is not None
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def password_needs_rehash(password_hash: str) -> bool:
    try:
        return _hasher.check_needs_rehash(password_hash)
    except InvalidHashError:
        return True


def validate_password_strength(password: str) -> None:
    settings = get_settings()
    problems = []
    if len(password) < settings.PASSWORD_MIN_LENGTH:
        problems.append(f"at least {settings.PASSWORD_MIN_LENGTH} characters")
    if not any(c.islower() for c in password):
        problems.append("a lowercase letter")
    if not any(c.isupper() for c in password):
        problems.append("an uppercase letter")
    if not any(c.isdigit() for c in password):
        problems.append("a digit")
    if problems:
        raise ValueError("Password must contain " + ", ".join(problems))


# --------------------------------------------------------------------- JWT
def create_access_token(
    *, subject: str, role: str, token_version: int, expires_minutes: int
) -> tuple[str, datetime]:
    settings = get_settings()
    issued = clock.now()
    expires = issued + timedelta(minutes=expires_minutes)
    payload: dict[str, Any] = {
        "sub": subject,
        "role": role,
        "ver": token_version,
        "iat": int(issued.timestamp()),
        "nbf": int(issued.timestamp()),
        "exp": int(expires.timestamp()),
        "iss": settings.JWT_ISSUER,
        "aud": settings.JWT_AUDIENCE,
        "jti": uuid.uuid4().hex,
    }
    token = jwt.encode(payload, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)
    return token, expires


def decode_access_token(token: str) -> dict[str, Any]:
    """Decode and validate a JWT. Raises ``jwt.PyJWTError`` on any problem."""
    settings = get_settings()
    payload: dict[str, Any] = jwt.decode(
        token,
        settings.JWT_SECRET_KEY,
        algorithms=[settings.JWT_ALGORITHM],  # never accept "none" or other algorithms
        audience=settings.JWT_AUDIENCE,
        issuer=settings.JWT_ISSUER,
        options={
            "require": ["exp", "iat", "sub", "role", "ver"],
            # Time claims are checked below against the application clock.
            "verify_exp": False,
            "verify_iat": False,
            "verify_nbf": False,
        },
    )
    now_ts = int(clock.now().timestamp())
    if int(payload["exp"]) <= now_ts:
        raise jwt.ExpiredSignatureError("Signature has expired")
    if int(payload.get("nbf", 0)) > now_ts + 30:
        raise jwt.ImmatureSignatureError("The token is not yet valid")
    return payload


# --------------------------------------------------------------- QR tokens
def generate_qr_token() -> str:
    """Opaque, URL-safe token with QR_TOKEN_BYTES (>= 32) bytes of CSPRNG entropy."""
    nbytes = max(32, get_settings().QR_TOKEN_BYTES)
    return secrets.token_urlsafe(nbytes)


def hash_token(token: str) -> str:
    """SHA-256 hex digest. Only this digest is stored in the database."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def qr_payload_for(token: str) -> str:
    """The exact string encoded in the QR image (prefix + opaque token, no PII)."""
    return f"{get_settings().QR_PAYLOAD_PREFIX}{token}"


def token_from_qr_payload(payload: str) -> str:
    payload = payload.strip()
    prefix = get_settings().QR_PAYLOAD_PREFIX
    return payload[len(prefix) :] if payload.startswith(prefix) else payload


def constant_time_equals(a: str, b: str) -> bool:
    return hmac.compare_digest(a.encode(), b.encode())


# ------------------------------------------------------- data encryption
def _fernet() -> Fernet:
    return Fernet(get_settings().DATA_ENCRYPTION_KEY.encode())


def encrypt_secret(plain: str) -> str:
    return _fernet().encrypt(plain.encode()).decode()


def decrypt_secret(cipher: str) -> str | None:
    try:
        return _fernet().decrypt(cipher.encode()).decode()
    except InvalidToken:
        return None
