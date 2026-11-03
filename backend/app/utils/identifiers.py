"""Public identifiers and masking helpers."""

from __future__ import annotations

import hashlib
import json
import re
import secrets
from typing import Any

# Crockford base32 without ambiguous characters (I, L, O, U).
_ALPHABET = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"
BOOKING_NUMBER_RE = re.compile(r"^MY26-[0-9A-HJKMNP-TV-Z]{8}$")


def new_booking_number() -> str:
    """e.g. MY26-7K3QX9PD -- 40 bits of randomness, not sequential, not guessable."""
    return "MY26-" + "".join(secrets.choice(_ALPHABET) for _ in range(8))


def normalize_booking_number(value: str) -> str:
    return (value or "").strip().upper()


def is_valid_booking_number(value: str) -> bool:
    return bool(BOOKING_NUMBER_RE.match(value))


def mask_mobile(mobile: str | None) -> str | None:
    if not mobile:
        return mobile
    return mobile[:2] + "*" * (len(mobile) - 4) + mobile[-2:]


def mask_email(email: str | None) -> str | None:
    if not email or "@" not in email:
        return email
    local, _, domain = email.partition("@")
    return (local[0] + "***" if local else "***") + "@" + domain


def canonical_hash(payload: Any) -> str:
    """Stable SHA-256 of a JSON-serialisable payload (used for idempotency)."""
    blob = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()
