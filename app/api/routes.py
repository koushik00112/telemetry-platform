import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError, OperationalError

from app.api.deps import DeviceDep, SessionDep, require_admin
from app.config import get_settings
from app.models import Device, Reading
from app.schemas import METRIC_PATTERN, DeviceCreate, DeviceCreated, ReadingIn, ReadingOut
from app.security import generate_api_key, hash_api_key

router = APIRouter()


@router.get("/healthz", tags=["ops"])
def healthz(session: SessionDep) -> dict[str, str]:
    try:
        session.execute(text("SELECT 1"))
    except OperationalError as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "database unavailable") from exc
    return {"status": "ok"}


@router.post(
    "/devices",
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_admin)],
    tags=["devices"],
)
def register_device(body: DeviceCreate, session: SessionDep) -> DeviceCreated:
    api_key = generate_api_key()
    device = Device(name=body.name, api_key_hash=hash_api_key(api_key))
    session.add(device)
    try:
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "device name already exists") from exc
    return DeviceCreated(id=device.id, name=device.name, api_key=api_key)


@router.post("/readings", status_code=status.HTTP_201_CREATED, tags=["readings"])
def ingest_reading(body: ReadingIn, device: DeviceDep, session: SessionDep) -> ReadingOut:
    reading = Reading(device_id=device.id, metric=body.metric, value=body.value, ts=body.ts)
    session.add(reading)
    session.commit()
    return ReadingOut.model_validate(reading)


@router.get("/devices/{device_id}/readings", tags=["readings"])
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
