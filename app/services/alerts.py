from collections import Counter, defaultdict

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.metrics import ALERTS_OPENED, ALERTS_RESOLVED
from app.models import Alert, AlertRule, AlertStatus, Reading


def evaluate(session: Session, rule: AlertRule, reading: Reading) -> AlertStatus | None:
    """Open an alert on the first breaching reading; resolve it on the next in-range one.

    Returns the transition that happened, if any.
    """
    open_alert = session.scalar(
        select(Alert).where(
            Alert.rule_id == rule.id,
            Alert.device_id == reading.device_id,
            Alert.status == AlertStatus.open,
        )
    )
    if rule.operator.breached(reading.value, rule.threshold):
        if open_alert is None:
            session.add(
                Alert(
                    rule_id=rule.id,
                    device_id=reading.device_id,
                    status=AlertStatus.open,
                    trigger_value=reading.value,
                    opened_at=reading.ts,
                )
            )
            # Flush so the next reading in this batch sees the alert as open.
            session.flush()
            return AlertStatus.open
    elif open_alert is not None:
        open_alert.status = AlertStatus.resolved
        open_alert.resolved_at = reading.ts
        return AlertStatus.resolved
    return None


def process_batch(session: Session, batch_size: int = 500) -> int:
    """Evaluate one batch of unchecked readings against all rules and commit.

    Rows are claimed with FOR UPDATE SKIP LOCKED, so several workers can run safely.
    Returns the number of readings processed.
    """
    readings = session.scalars(
        select(Reading)
        .where(Reading.alert_checked.is_(False))
        .order_by(Reading.ts, Reading.id)
        .limit(batch_size)
        .with_for_update(skip_locked=True)
    ).all()
    if not readings:
        return 0

    metrics = {r.metric for r in readings}
    rules: dict[str, list[AlertRule]] = defaultdict(list)
    for rule in session.scalars(select(AlertRule).where(AlertRule.metric.in_(metrics))):
        rules[rule.metric].append(rule)

    transitions: Counter[AlertStatus] = Counter()
    for reading in readings:
        for rule in rules[reading.metric]:
            if (change := evaluate(session, rule, reading)) is not None:
                transitions[change] += 1
        reading.alert_checked = True
    session.commit()
    # Count only after commit, so a rolled-back batch isn't counted twice on retry.
    ALERTS_OPENED.inc(transitions[AlertStatus.open])
    ALERTS_RESOLVED.inc(transitions[AlertStatus.resolved])
    return len(readings)


def backlog(session: Session) -> int:
    """Readings not yet evaluated. Served by the partial index on unchecked rows."""
    return (
        session.scalar(
            select(func.count()).select_from(Reading).where(Reading.alert_checked.is_(False))
        )
        or 0
    )
