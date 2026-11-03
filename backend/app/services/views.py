"""Small, shared serialisers for API payloads."""

from __future__ import annotations

from typing import Any

from app.models import FamilyMember


def member_dict(m: FamilyMember) -> dict[str, Any]:
    return {
        "member_number": m.member_number,
        "full_name": m.full_name,
        "age": m.age,
        "gender": m.gender,
        "relationship": m.relationship_,
    }
