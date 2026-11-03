"""Family registration: validation -> booking -> members -> allocation -> QR, atomically.

Transaction outline (single transaction, retried as a whole on transient
lock errors):

  1. Claim the Idempotency-Key (INSERT ... ON CONFLICT DO NOTHING). A
     concurrent duplicate waits on the first and then replays its response.
  2. Advisory lock on the coordinator's mobile + duplicate-booking check.
  3. Validate sessions (exist / active / open / before cut-off).
  4. Insert booking (random, unique booking number) and family members.
  5. Issue the family QR pass.
  6. Allocate one Kund per selected session (AllocationService) -- any
     failure rolls back EVERYTHING above.
  7. Store the response on the idempotency record (QR token encrypted,
     short-lived) and write the audit log.
  8. COMMIT.

Capacity locks are taken as late as possible (step 6) to keep the time they
are held short.
"""

from __future__ import annotations

import copy
import logging
from datetime import date, timedelta
from typing import Any

from fastapi.encoders import jsonable_encoder
from sqlalchemy.orm import Session

from app.core import clock, security
from app.core.config import get_settings
from app.core.database import run_transaction
from app.core.errors import AppError, CapacityUnavailable, Conflict, ValidationFailed
from app.models.enums import BookingStatus
from app.repositories.booking_repository import BookingRepository
from app.repositories.misc_repositories import IdempotencyRepository
from app.repositories.session_repository import SessionRepository
from app.schemas.registration import RegistrationRequest
from app.services import session_service
from app.services.allocation_service import AllocationService
from app.services.audit_service import RequestContext, audit
from app.services.qr_service import QrService
from app.utils.identifiers import canonical_hash, mask_mobile, new_booking_number

logger = logging.getLogger("app.registration")

IDEMPOTENCY_SCOPE = "registration"
QR_IMAGE_ENDPOINT = "/api/v1/qr/pass/image"


class RegistrationResult:
    def __init__(self, payload: dict[str, Any], *, replayed: bool) -> None:
        self.payload = payload
        self.replayed = replayed


class RegistrationService:
    def __init__(self, db: Session) -> None:
        self.db = db

    def register(
        self, request: RegistrationRequest, *, idempotency_key: str | None, ctx: RequestContext
    ) -> RegistrationResult:
        settings = get_settings()
        request_hash = canonical_hash(request.model_dump(mode="json"))

        def work(db: Session) -> RegistrationResult:
            idem = IdempotencyRepository(db)
            record_id: int | None = None
            if idempotency_key:
                record_id = idem.claim(
                    scope=IDEMPOTENCY_SCOPE,
                    key=idempotency_key,
                    request_hash=request_hash,
                    expires_at=clock.now() + timedelta(hours=settings.IDEMPOTENCY_TTL_HOURS),
                )
                if record_id is None:
                    return self._replay(idem, idempotency_key, request_hash)
            return self._create(db, request, record_id=record_id, ctx=ctx)

        try:
            return run_transaction(self.db, work, label="registration")
        except CapacityUnavailable as exc:
            exc.details = {
                **(exc.details or {}),
                "availability": self.availability(request.selected_sessions, len(request.members)),
            }
            raise

    # ------------------------------------------------------------ internals
    def _replay(self, idem: IdempotencyRepository, key: str, request_hash: str) -> RegistrationResult:
        record = idem.get(scope=IDEMPOTENCY_SCOPE, key=key)
        if record is None:  # pragma: no cover - only possible if purged mid-flight
            raise Conflict("Please retry the request", code="IDEMPOTENCY_RETRY")
        if not security.constant_time_equals(record.request_hash, request_hash):
            raise AppError(
                "This Idempotency-Key was already used with a different request body",
                code="IDEMPOTENCY_KEY_REUSED",
                status_code=422,
            )
        if record.status != "COMPLETED" or record.response_payload is None:
            raise Conflict("The original request is still being processed. Retry shortly.", code="IDEMPOTENCY_IN_PROGRESS")
        payload = copy.deepcopy(record.response_payload)
        token = security.decrypt_secret(record.encrypted_secret) if record.encrypted_secret else None
        qr = payload.get("qr_pass", {})
        if token:
            qr["token"] = token
            qr["qr_payload"] = security.qr_payload_for(token)
        else:
            qr["note"] = (
                "The pass token is no longer available for replay. Use the pass you received, "
                "or ask the help desk to re-issue the QR pass."
            )
        return RegistrationResult(payload, replayed=True)

    def _create(
        self, db: Session, request: RegistrationRequest, *, record_id: int | None, ctx: RequestContext
    ) -> RegistrationResult:
        settings = get_settings()
        bookings = BookingRepository(db)
        sessions_repo = SessionRepository(db)
        c = request.coordinator
        family_size = len(request.members)
        session_ids = request.selected_sessions

        # 2. session validation (re-checked under lock during allocation)
        sessions = {s.id: s for s in sessions_repo.get_many(session_ids)}
        invalid = [sid for sid in session_ids if sid not in sessions]
        if invalid:
            raise ValidationFailed(
                "One or more selected sessions do not exist", code="INVALID_SESSION",
                details={"invalid_sessions": invalid},
            )

        # 3. one session per day: a booking may not include both the morning and the afternoon
        #    session of the same date.
        if settings.ONE_SESSION_PER_DAY:
            by_date: dict[date, list[int]] = {}
            for sid in session_ids:
                by_date.setdefault(sessions[sid].event_date, []).append(sid)
            twice = {d.isoformat(): ids for d, ids in by_date.items() if len(ids) > 1}
            if twice:
                raise ValidationFailed(
                    "Only one session (morning or afternoon) can be booked per day",
                    code="ONE_SESSION_PER_DAY",
                    details={"dates": sorted(twice), "sessions": sorted(i for ids in twice.values() for i in ids)},
                )

        # 4. duplicate-booking guard (serialised per mobile number)
        if settings.ENFORCE_UNIQUE_MOBILE_PER_SESSION:
            bookings.lock_mobile(c.primary_mobile)
            dup = bookings.confirmed_sessions_for_mobile(c.primary_mobile, session_ids)
            if dup:
                raise Conflict(
                    "A confirmed booking already exists for this mobile number in the selected session(s)",
                    code="DUPLICATE_BOOKING",
                    details={"sessions": dup},
                )
            if settings.ONE_SESSION_PER_DAY:
                busy_days = bookings.confirmed_dates_for_mobile(
                    c.primary_mobile, sorted({s.event_date for s in sessions.values()})
                )
                if busy_days:
                    raise Conflict(
                        "This mobile number already has a booking on the selected day(s). "
                        "Only one session can be booked per day.",
                        code="DUPLICATE_BOOKING",
                        details={"dates": [d.isoformat() for d in busy_days]},
                    )
        blocked = [
            {"session_id": sid, "reason": reason}
            for sid in session_ids
            if (reason := session_service.booking_block_reason(sessions[sid]))
        ]
        if blocked:
            raise ValidationFailed(
                "One or more selected sessions are not open for booking", code="SESSION_NOT_BOOKABLE",
                details={"sessions": blocked},
            )

        # 4. booking + members
        values = {
            "coordinator_name": c.name,
            "primary_mobile": c.primary_mobile,
            "secondary_mobile": c.secondary_mobile,
            "email": c.email,
            "address": c.address,
            "city": c.city,
            "state": c.state,
            "pincode": c.pincode,
            "gotra": c.gotra,
            "sankalp_purpose": c.sankalp_purpose,
            "member_count": family_size,
            "status": BookingStatus.CONFIRMED.value,
        }
        booking_id = None
        booking_number = ""
        for _ in range(8):
            booking_number = new_booking_number()
            booking_id = bookings.try_insert_booking({**values, "booking_number": booking_number})
            if booking_id is not None:
                break
        if booking_id is None:  # pragma: no cover - ~impossible with 40-bit numbers
            raise Conflict("Could not allocate a booking number, please retry", code="BOOKING_NUMBER_RETRY")
        members = bookings.insert_members(
            booking_id,
            [
                {
                    "full_name": m.full_name,
                    "age": m.age,
                    "gender": m.gender,
                    "relationship": m.relationship or ("Self" if i == 0 else None),
                    "mobile": m.mobile,
                }
                for i, m in enumerate(request.members)
            ],
        )

        # 5. QR pass (issued before allocation so the capacity locks taken in
        #    step 6 are held for as short a time as possible)
        issued = QrService(db).issue(booking_id, revoke_reason="REGENERATED")

        # 6. allocation (all-or-nothing)
        allocations = AllocationService(db).allocate_family(
            booking_id=booking_id, family_size=family_size, session_ids=session_ids
        )

        payload: dict[str, Any] = jsonable_encoder(
            {
                "booking_number": booking_number,
                "status": BookingStatus.CONFIRMED.value,
                "coordinator_name": c.name,
                "primary_mobile_masked": mask_mobile(c.primary_mobile),
                "member_count": family_size,
                "members": members,
                "reservations": [
                    {
                        "session_id": a.session_id,
                        "event_date": sessions[a.session_id].event_date,
                        "slot": sessions[a.session_id].slot,
                        "start_time": sessions[a.session_id].start_time,
                        "end_time": sessions[a.session_id].end_time,
                        "kund_number": a.kund_number,
                        "member_count": family_size,
                        "status": "CONFIRMED",
                    }
                    for a in allocations
                ],
                "qr_pass": {
                    "token": None,
                    "qr_payload": None,
                    "expires_at": issued.expires_at,
                    "image_endpoint": QR_IMAGE_ENDPOINT,
                    "note": None,
                },
                "created_at": clock.now(),
            }
        )

        # 7. idempotency record (token stored only encrypted, for replay) + audit
        if record_id is not None:
            IdempotencyRepository(db).complete(
                record_id,
                response_status=201,
                payload=payload,
                encrypted_secret=security.encrypt_secret(issued.token),
                resource_id=booking_id,
            )
        audit(
            db, ctx, action="BOOKING_CREATED", entity_type="booking", entity_id=booking_number,
            new={
                "member_count": family_size,
                "allocations": [{"session_id": a.session_id, "kund_number": a.kund_number} for a in allocations],
            },
        )

        result_payload = copy.deepcopy(payload)
        result_payload["qr_pass"]["token"] = issued.token
        result_payload["qr_pass"]["qr_payload"] = issued.qr_payload
        logger.info("booking_created", extra={"booking_number": booking_number, "sessions": len(allocations)})
        return RegistrationResult(result_payload, replayed=False)

    def availability(self, session_ids: list[int], family_size: int) -> list[dict[str, Any]]:
        """Non-locking availability snapshot used to explain a capacity failure."""
        self.db.rollback()
        stats = SessionRepository(self.db).capacity_stats(session_ids)
        return [
            {
                "session_id": sid,
                "remaining_places": stats[sid].remaining if sid in stats else 0,
                "largest_family_bookable": stats[sid].largest_free_block if sid in stats else 0,
                "fits_this_family": bool(sid in stats and stats[sid].largest_free_block >= family_size),
            }
            for sid in session_ids
        ]
