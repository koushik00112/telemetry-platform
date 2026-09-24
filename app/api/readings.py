import hashlib
import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Header, HTTPException, Query, Response, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.api.deps import DeviceDep, SessionDep
from app.config import get_settings
from app.models import IdempotencyKey, Reading
from app.schemas import METRIC_PATTERN, ReadingBatchIn, ReadingBatchResult, ReadingIn, ReadingOut
from app.services.ingest import insert_readings

router = APIRouter(tags=["readings"])


@router.post(
    "/readings",
    status_code=status.HTTP_201_CREATED,
    responses={200: {"description": "Duplicate of a stored reading; the stored one is returned"}},
)
def ingest_reading(
    body: ReadingIn, device: DeviceDep, session: SessionDep, response: Response
) -> ReadingOut:
    inserted = insert_readings(session, device.id, [body])
    session.commit()
    if not inserted:
        response.status_code = status.HTTP_200_OK
    stored = session.scalars(
        select(Reading).where(
            Reading.device_id == device.id, Reading.metric == body.metric, Reading.ts == body.ts
        )
    ).one()
    return ReadingOut.model_validate(stored)


@router.post("/readings/batch", status_code=status.HTTP_200_OK)
def ingest_batch(
    body: ReadingBatchIn,
    device: DeviceDep,
    session: SessionDep,
    response: Response,
    idempotency_key: Annotated[str | None, Header(max_length=128)] = None,
) -> ReadingBatchResult:
    """Insert up to 1000 readings. Duplicates are skipped and counted, not rejected.

    With an Idempotency-Key header, a retry with the same key and body returns the
    original result; the same key with a different body is rejected with 422.
    """
    request_hash = hashlib.sha256(body.model_dump_json().encode()).hexdigest()
    if idempotency_key is not None:
        replay = _replay(session, device.id, idempotency_key, request_hash, response)
        if replay is not None:
            return replay

    inserted = insert_readings(session, device.id, body.readings)
    result = ReadingBatchResult(
        received=len(body.readings), inserted=inserted, duplicates=len(body.readings) - inserted
    )
    if idempotency_key is not None:
        session.add(
            IdempotencyKey(
                device_id=device.id,
                key=idempotency_key,
                request_hash=request_hash,
                response=result.model_dump(),
            )
        )
    try:
        session.commit()
    except IntegrityError:
        # A concurrent request with the same key committed first; return its result.
        session.rollback()
        replay = _replay(session, device.id, idempotency_key or "", request_hash, response)
        if replay is None:
            raise
        return replay
    return result


def _replay(
    session: SessionDep, device_id: uuid.UUID, key: str, request_hash: str, response: Response
) -> ReadingBatchResult | None:
    stored = session.get(IdempotencyKey, (device_id, key))
    if stored is None:
        return None
    if stored.request_hash != request_hash:
        raise HTTPException(422, "Idempotency-Key was already used with a different request body")
    response.headers["Idempotent-Replayed"] = "true"
    return ReadingBatchResult.model_validate(stored.response)


@router.get("/devices/{device_id}/readings")
def query_readings(
    device_id: uuid.UUID,
    device: DeviceDep,
    session: SessionDep,
    start: datetime,
    end: datetime,
    metric: Annotated[str | None, Query(pattern=METRIC_PATTERN)] = None,
    limit: Annotated[int, Query(ge=1)] = 1000,
) -> list[ReadingOut]:
    # A device key can only read its own data. Operator read access comes later.
    if device.id != device_id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "cannot read another device's data")
    if start.tzinfo is None or end.tzinfo is None:
        raise HTTPException(422, "start/end need a timezone")
    if end <= start:
        raise HTTPException(422, "end must be after start")
    stmt = (
        select(Reading)
        .where(Reading.device_id == device_id, Reading.ts >= start, Reading.ts < end)
        .order_by(Reading.ts)
        .limit(min(limit, get_settings().max_query_rows))
    )
    if metric is not None:
        stmt = stmt.where(Reading.metric == metric)
    return [ReadingOut.model_validate(r) for r in session.scalars(stmt)]
