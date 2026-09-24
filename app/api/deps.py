from typing import Annotated

from fastapi import Depends, Header, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import get_session
from app.models import Device
from app.security import hash_api_key, tokens_equal

SessionDep = Annotated[Session, Depends(get_session)]


def require_admin(x_admin_token: Annotated[str | None, Header()] = None) -> None:
    if x_admin_token is None or not tokens_equal(x_admin_token, get_settings().admin_token):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid admin token")


def current_device(
    session: SessionDep, x_api_key: Annotated[str | None, Header()] = None
) -> Device:
    if not x_api_key:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "missing X-API-Key header")
    device = session.scalar(select(Device).where(Device.api_key_hash == hash_api_key(x_api_key)))
    if device is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid API key")
    return device


DeviceDep = Annotated[Device, Depends(current_device)]
