import uuid
from collections.abc import Sequence

from sqlalchemy import Insert
from sqlalchemy.dialects import postgresql, sqlite
from sqlalchemy.orm import Session

from app.models import Reading
from app.schemas import ReadingIn


def _insert(session: Session) -> Insert:
    # ON CONFLICT is dialect-specific in SQLAlchemy; Postgres in prod, SQLite in unit tests.
    dialect = session.get_bind().dialect.name
    if dialect == "postgresql":
        return postgresql.insert(Reading)
    if dialect == "sqlite":
        return sqlite.insert(Reading)
    raise RuntimeError(f"unsupported database dialect: {dialect}")


def insert_readings(session: Session, device_id: uuid.UUID, readings: Sequence[ReadingIn]) -> int:
    """Insert readings, silently skipping duplicates of (device, metric, ts).

    Returns how many rows were actually inserted. Does not commit.
    """
    if not readings:
        return 0
    rows = [
        {"device_id": device_id, "metric": r.metric, "value": r.value, "ts": r.ts} for r in readings
    ]
    stmt = (
        _insert(session)  # type: ignore[attr-defined]
        .values(rows)
        .on_conflict_do_nothing(index_elements=["device_id", "metric", "ts"])
        .returning(Reading.id)
    )
    return len(session.execute(stmt).all())
