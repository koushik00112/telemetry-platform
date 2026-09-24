import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy import select

from app.api.deps import SessionDep, require_admin
from app.models import Alert, AlertRule, AlertStatus
from app.schemas import AlertOut, AlertRuleIn, AlertRuleOut

router = APIRouter(tags=["alerts"], dependencies=[Depends(require_admin)])


@router.post("/alert-rules", status_code=status.HTTP_201_CREATED)
def create_rule(body: AlertRuleIn, session: SessionDep) -> AlertRuleOut:
    rule = AlertRule(**body.model_dump())
    session.add(rule)
    session.commit()
    return AlertRuleOut.model_validate(rule)


@router.get("/alert-rules")
def list_rules(session: SessionDep) -> list[AlertRuleOut]:
    rules = session.scalars(select(AlertRule).order_by(AlertRule.id))
    return [AlertRuleOut.model_validate(r) for r in rules]


@router.get("/alerts")
def list_alerts(
    session: SessionDep,
    alert_status: Annotated[AlertStatus | None, Query(alias="status")] = None,
    device_id: uuid.UUID | None = None,
    limit: Annotated[int, Query(ge=1, le=1000)] = 100,
) -> list[AlertOut]:
    stmt = select(Alert).order_by(Alert.opened_at.desc()).limit(limit)
    if alert_status is not None:
        stmt = stmt.where(Alert.status == alert_status)
    if device_id is not None:
        stmt = stmt.where(Alert.device_id == device_id)
    return [AlertOut.model_validate(a) for a in session.scalars(stmt)]
