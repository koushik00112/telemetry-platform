import enum
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    Uuid,
    false,
    text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def utcnow() -> datetime:
    return datetime.now(UTC)


class Base(DeclarativeBase):
    pass


class Device(Base):
    __tablename__ = "devices"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(100), unique=True)
    # Only a SHA-256 hash of the key is stored; the plaintext is shown once at registration.
    api_key_hash: Mapped[str] = mapped_column(String(64), unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Reading(Base):
    __tablename__ = "readings"

    # BIGINT on Postgres; SQLite only autoincrements a plain INTEGER primary key.
    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer(), "sqlite"), primary_key=True, autoincrement=True
    )
    device_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("devices.id", ondelete="CASCADE"))
    metric: Mapped[str] = mapped_column(String(64))
    value: Mapped[float] = mapped_column(Float)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    # Set by the alert worker once the reading has been evaluated. See ADR 0002.
    alert_checked: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())

    __table_args__ = (
        # A device reports one value per metric per instant; resends are duplicates.
        UniqueConstraint("device_id", "metric", "ts", name="uq_readings_device_metric_ts"),
        Index(
            "ix_readings_unchecked",
            "ts",
            postgresql_where=text("NOT alert_checked"),
            sqlite_where=text("NOT alert_checked"),
        ),
    )


class IdempotencyKey(Base):
    """Stores the response to a keyed batch request so a retry gets the same answer."""

    __tablename__ = "idempotency_keys"

    device_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("devices.id", ondelete="CASCADE"), primary_key=True
    )
    key: Mapped[str] = mapped_column(String(128), primary_key=True)
    request_hash: Mapped[str] = mapped_column(String(64))
    response: Mapped[dict[str, Any]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Operator(enum.StrEnum):
    gt = "gt"
    lt = "lt"

    def breached(self, value: float, threshold: float) -> bool:
        return value > threshold if self is Operator.gt else value < threshold


class AlertRule(Base):
    __tablename__ = "alert_rules"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    metric: Mapped[str] = mapped_column(String(64), index=True)
    operator: Mapped[Operator] = mapped_column(Enum(Operator, name="alert_operator"))
    threshold: Mapped[float] = mapped_column(Float)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class AlertStatus(enum.StrEnum):
    open = "open"
    resolved = "resolved"


class Alert(Base):
    """Opens when a device breaches a rule and resolves on its next in-range reading."""

    __tablename__ = "alerts"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    rule_id: Mapped[int] = mapped_column(ForeignKey("alert_rules.id", ondelete="CASCADE"))
    device_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("devices.id", ondelete="CASCADE"))
    status: Mapped[AlertStatus] = mapped_column(Enum(AlertStatus, name="alert_status"))
    trigger_value: Mapped[float] = mapped_column(Float)
    opened_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        # At most one open alert per (rule, device), even with concurrent workers.
        Index(
            "uq_alerts_one_open",
            "rule_id",
            "device_id",
            unique=True,
            postgresql_where=text("status = 'open'"),
            sqlite_where=text("status = 'open'"),
        ),
    )
