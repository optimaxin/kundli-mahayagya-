"""Pure unit tests (no database)."""

from __future__ import annotations

import hashlib
import re
from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from app.core import clock, security
from app.core.rate_limit import MemoryBackend, RateSpec
from app.schemas.registration import RegistrationRequest
from app.services.xlsx_stream import XlsxStream
from app.utils import validators as v
from app.utils.identifiers import (
    BOOKING_NUMBER_RE,
    canonical_hash,
    is_valid_booking_number,
    mask_email,
    mask_mobile,
    new_booking_number,
)
from tests.conftest import registration_payload


@pytest.mark.parametrize(
    "raw,expected",
    [("9876543210", "9876543210"), ("+91 98765 43210", "9876543210"), ("09876543210", "9876543210"),
     ("919876543210", "9876543210"), ("98765-43210", "9876543210")],
)
def test_mobile_normalisation(raw: str, expected: str) -> None:
    assert v.normalize_mobile(raw) == expected


@pytest.mark.parametrize("raw", ["5876543210", "987654321", "98765432100", "abcdefghij", ""])
def test_invalid_mobiles(raw: str) -> None:
    with pytest.raises(ValueError):
        v.normalize_mobile(raw)


def test_names_accept_indian_scripts_and_reject_symbols() -> None:
    assert v.validate_person_name("  राहुल   शर्मा ") == "राहुल शर्मा"
    assert v.validate_person_name("S. O'Neil-Iyer") == "S. O'Neil-Iyer"
    for bad in ("R2D2", "<script>", "A", "Ram@Kumar", "x" * 101):
        with pytest.raises(ValueError):
            v.validate_person_name(bad)


def test_state_and_pincode() -> None:
    assert v.canonical_state("uttar pradesh") == "Uttar Pradesh"
    assert v.canonical_state("Jammu & Kashmir") == "Jammu and Kashmir"
    assert v.validate_pincode("282 001") == "282001"
    with pytest.raises(ValueError):
        v.validate_pincode("012345")
    with pytest.raises(ValueError):
        v.canonical_state("Atlantis")


def test_free_text_rejects_markup_and_control_chars() -> None:
    assert v.validate_free_text("Line1\x00\nLine2", field="A", min_len=1, max_len=50) == "Line1 Line2"
    with pytest.raises(ValueError):
        v.validate_free_text("<b>x</b>", field="A", min_len=1, max_len=50)


def test_booking_numbers() -> None:
    numbers = {new_booking_number() for _ in range(2000)}
    assert len(numbers) == 2000
    assert all(BOOKING_NUMBER_RE.match(n) for n in numbers)
    assert not any(c in n[5:] for n in numbers for c in "ILOU")
    assert is_valid_booking_number("MY26-7K3QX9PD") and not is_valid_booking_number("MY26-7K3QX9PO")


def test_masking() -> None:
    assert mask_mobile("9876543210") == "98******10"
    assert mask_email("rahul@example.com") == "r***@example.com"


def test_qr_tokens_are_random_hashed_and_prefixed() -> None:
    tokens = {security.generate_qr_token() for _ in range(1000)}
    assert len(tokens) == 1000
    t = next(iter(tokens))
    assert len(t) >= 43 and re.fullmatch(r"[A-Za-z0-9_\-]+", t)
    assert security.hash_token(t) == hashlib.sha256(t.encode()).hexdigest()
    payload = security.qr_payload_for(t)
    assert payload == "MY26." + t and security.token_from_qr_payload(payload) == t


def test_password_hashing() -> None:
    h = security.hash_password("Correct-Horse-9")
    assert h.startswith("$argon2id$") and "Correct" not in h
    assert security.verify_password("Correct-Horse-9", h)
    assert not security.verify_password("wrong", h)
    assert not security.verify_password("anything", None)
    with pytest.raises(ValueError):
        security.validate_password_strength("short")


def test_jwt_roundtrip_and_expiry() -> None:
    clock.freeze(datetime(2026, 12, 1, tzinfo=UTC))
    try:
        token, exp = security.create_access_token(subject="abc", role="ADMIN", token_version=3, expires_minutes=5)
        claims = security.decode_access_token(token)
        assert claims["sub"] == "abc" and claims["ver"] == 3
        clock.freeze(exp)
        import jwt

        with pytest.raises(jwt.ExpiredSignatureError):
            security.decode_access_token(token)
    finally:
        clock.freeze(None)


def test_encryption_roundtrip() -> None:
    c = security.encrypt_secret("token-value")
    assert "token-value" not in c and security.decrypt_secret(c) == "token-value"
    assert security.decrypt_secret("garbage") is None


def test_rate_limiter() -> None:
    assert RateSpec.parse("10/minute") == RateSpec(10, 60)
    assert RateSpec.parse("5/seconds") == RateSpec(5, 1)
    backend = MemoryBackend()
    spec = RateSpec(3, 60)
    results = [backend.hit("k", spec)[0] for _ in range(5)]
    assert results == [True, True, True, False, False]
    assert backend.hit("other", spec)[0] is True


def test_canonical_hash_is_order_independent() -> None:
    assert canonical_hash({"a": 1, "b": [1, 2]}) == canonical_hash({"b": [1, 2], "a": 1})
    assert canonical_hash({"a": 1}) != canonical_hash({"a": 2})


def test_registration_schema() -> None:
    req = RegistrationRequest.model_validate(registration_payload(members=8, sessions=[3, 1, 2]))
    assert req.selected_sessions == [1, 2, 3] and len(req.members) == 8
    assert req.coordinator.secondary_mobile is None
    with pytest.raises(ValidationError, match="at most 8"):
        RegistrationRequest.model_validate(registration_payload(members=9))
    with pytest.raises(ValidationError, match="different from the primary"):
        RegistrationRequest.model_validate(
            registration_payload(primary_mobile="9876543210", secondary_mobile="+919876543210")
        )


def test_excel_formula_injection_neutralised() -> None:
    import io

    from openpyxl import load_workbook

    buf = io.BytesIO()
    with XlsxStream(buf) as book, book.sheet("S", ["h"]) as sheet:
        sheet.append(["=1+1", "+91 phone", "normal", 5])
    assert [c.value for c in load_workbook(io.BytesIO(buf.getvalue()))["S"][2]] == ["'=1+1", "'+91 phone", "normal", 5]
