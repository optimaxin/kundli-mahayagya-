"""Input normalisation and validation helpers (Unicode-aware, India-specific)."""

from __future__ import annotations

import re
import unicodedata

INDIAN_STATES_AND_UTS: tuple[str, ...] = (
    "Andhra Pradesh", "Arunachal Pradesh", "Assam", "Bihar", "Chhattisgarh", "Goa", "Gujarat",
    "Haryana", "Himachal Pradesh", "Jharkhand", "Karnataka", "Kerala", "Madhya Pradesh",
    "Maharashtra", "Manipur", "Meghalaya", "Mizoram", "Nagaland", "Odisha", "Punjab", "Rajasthan",
    "Sikkim", "Tamil Nadu", "Telangana", "Tripura", "Uttar Pradesh", "Uttarakhand", "West Bengal",
    "Andaman and Nicobar Islands", "Chandigarh", "Dadra and Nagar Haveli and Daman and Diu",
    "Delhi", "Jammu and Kashmir", "Ladakh", "Lakshadweep", "Puducherry",
)  # fmt: skip
_STATE_LOOKUP = {s.lower(): s for s in INDIAN_STATES_AND_UTS}
_STATE_LOOKUP.update({"nct of delhi": "Delhi", "orissa": "Odisha", "pondicherry": "Puducherry", "other": "Other"})

_MOBILE_RE = re.compile(r"^[6-9]\d{9}$")
_PINCODE_RE = re.compile(r"^[1-9]\d{5}$")
_NAME_PUNCT = set(" .'-")
_FORBIDDEN_TEXT_CHARS = set("<>{}`\\")


def clean_text(value: str) -> str:
    """NFC-normalise, drop control/format characters, collapse whitespace."""
    value = unicodedata.normalize("NFC", value)
    value = "".join(
        ch if not unicodedata.category(ch).startswith("C") else " " for ch in value
    )
    return " ".join(value.split())


def validate_person_name(value: str, *, field: str = "Name") -> str:
    value = clean_text(value)
    if not 2 <= len(value) <= 100:
        raise ValueError(f"{field} must be between 2 and 100 characters")
    letters = 0
    for ch in value:
        cat = unicodedata.category(ch)
        if cat.startswith("L"):
            letters += 1
        elif cat.startswith("M") or ch in _NAME_PUNCT:
            continue
        else:
            raise ValueError(f"{field} may contain only letters, spaces, '.', apostrophe and '-'")
    if letters < 2:
        raise ValueError(f"{field} must contain at least 2 letters")
    return value


def validate_free_text(value: str, *, field: str, min_len: int, max_len: int) -> str:
    value = clean_text(value)
    if not min_len <= len(value) <= max_len:
        raise ValueError(f"{field} must be between {min_len} and {max_len} characters")
    if any(ch in _FORBIDDEN_TEXT_CHARS for ch in value):
        raise ValueError(f"{field} contains characters that are not allowed (< > {{ }} ` \\)")
    return value


def normalize_mobile(value: str, *, field: str = "Mobile number") -> str:
    digits = re.sub(r"[\s\-()]", "", value or "")
    if digits.startswith("+91"):
        digits = digits[3:]
    elif len(digits) == 12 and digits.startswith("91"):
        digits = digits[2:]
    elif len(digits) == 11 and digits.startswith("0"):
        digits = digits[1:]
    if not _MOBILE_RE.match(digits):
        raise ValueError(f"{field} must be a valid 10-digit Indian mobile number starting with 6-9")
    return digits


def validate_pincode(value: str) -> str:
    value = (value or "").strip().replace(" ", "")
    if not _PINCODE_RE.match(value):
        raise ValueError("Pincode must be a valid 6-digit Indian PIN code")
    return value


def canonical_state(value: str) -> str:
    key = clean_text(value).lower().replace("&", "and")
    if key not in _STATE_LOOKUP:
        raise ValueError("State must be a valid Indian state or union territory")
    return _STATE_LOOKUP[key]
