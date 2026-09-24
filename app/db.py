from collections.abc import Iterator
from functools import lru_cache
from typing import Any

from sqlalchemy import Engine, create_engine, make_url
from sqlalchemy.orm import Session, sessionmaker

from app.config import get_settings


@lru_cache
def get_engine() -> Engine:
    url = make_url(get_settings().database_url)
    connect_args: dict[str, Any] = {}
    if url.get_backend_name() == "postgresql":
        # Without a timeout, an unreachable DB hangs requests instead of failing fast with 503.
        connect_args["connect_timeout"] = 5
    return create_engine(url, pool_pre_ping=True, connect_args=connect_args)


def get_session() -> Iterator[Session]:
    factory = sessionmaker(bind=get_engine(), expire_on_commit=False)
    with factory() as session:
        yield session
