from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError, OperationalError

from app.api.deps import SessionDep, require_admin
from app.models import Device
from app.schemas import DeviceCreate, DeviceCreated
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
