import uuid
from datetime import UTC, datetime, timedelta

import pytest

from app.models import Alert, AlertRule, AlertStatus, Device, Operator, Reading
from app.services.alerts import process_batch
from tests.unit.conftest import ADMIN

T0 = datetime(2026, 9, 28, 12, 0, tzinfo=UTC)


@pytest.fixture
def db(session_factory):
    with session_factory() as s:
        yield s


def add_device(db, name="dev-1"):
    d = Device(id=uuid.uuid4(), name=name, api_key_hash=uuid.uuid4().hex)
    db.add(d)
    db.commit()
    return d


def add_readings(db, device, values, metric="temperature_c"):
    for i, v in enumerate(values):
        db.add(Reading(device_id=device.id, metric=metric, value=v, ts=T0 + timedelta(minutes=i)))
    db.commit()


def alerts(db):
    return db.query(Alert).order_by(Alert.id).all()


@pytest.mark.parametrize(
    ("operator", "value", "threshold", "breached"),
    [("gt", 31, 30, True), ("gt", 30, 30, False), ("lt", 9, 10, True), ("lt", 10, 10, False)],
)
def test_operator_boundaries(operator, value, threshold, breached):
    assert Operator(operator).breached(value, threshold) is breached


def test_alert_opens_once_per_breach_and_resolves(db):
    device = add_device(db)
    db.add(AlertRule(metric="temperature_c", operator=Operator.gt, threshold=30))
    add_readings(db, device, [25, 35, 36, 37, 25])

    assert process_batch(db) == 5
    [alert] = alerts(db)
    assert alert.status is AlertStatus.resolved
    assert alert.trigger_value == 35
    assert alert.opened_at.replace(tzinfo=UTC) == T0 + timedelta(minutes=1)
    assert alert.resolved_at.replace(tzinfo=UTC) == T0 + timedelta(minutes=4)


def test_a_second_breach_opens_a_new_alert(db):
    device = add_device(db)
    db.add(AlertRule(metric="temperature_c", operator=Operator.gt, threshold=30))
    add_readings(db, device, [35, 20, 40])
    process_batch(db)
    assert [a.status for a in alerts(db)] == [AlertStatus.resolved, AlertStatus.open]


def test_alert_state_carries_across_batches(db):
    device = add_device(db)
    db.add(AlertRule(metric="temperature_c", operator=Operator.gt, threshold=30))
    add_readings(db, device, [35, 36, 37, 38])
    assert process_batch(db, batch_size=2) == 2
    assert process_batch(db, batch_size=2) == 2
    assert process_batch(db, batch_size=2) == 0
    assert len(alerts(db)) == 1


def test_alerts_are_per_device_and_ignore_other_metrics(db):
    a, b = add_device(db, "a"), add_device(db, "b")
    db.add(AlertRule(metric="temperature_c", operator=Operator.gt, threshold=30))
    add_readings(db, a, [35])
    add_readings(db, b, [35])
    add_readings(db, b, [99], metric="humidity_pct")
    process_batch(db)
    assert sorted(x.device_id for x in alerts(db)) == sorted([a.id, b.id])


def test_readings_are_marked_checked_even_without_rules(db):
    add_readings(db, add_device(db), [1, 2, 3])
    assert process_batch(db) == 3
    assert db.query(Reading).filter(Reading.alert_checked.is_(False)).count() == 0
    assert process_batch(db) == 0


def test_alert_endpoints_require_admin(client):
    assert client.get("/alerts").status_code == 401
    assert client.get("/alert-rules").status_code == 401
    rule = {"metric": "temperature_c", "operator": "gt", "threshold": 30}
    assert client.post("/alert-rules", json=rule).status_code == 401


def test_rule_crud_and_alert_listing(client, session_factory):
    rule = {"metric": "temperature_c", "operator": "gt", "threshold": 30}
    created = client.post("/alert-rules", json=rule, headers=ADMIN)
    assert created.status_code == 201
    assert client.get("/alert-rules", headers=ADMIN).json() == [created.json()]
    bad = {**rule, "operator": "gte"}
    assert client.post("/alert-rules", json=bad, headers=ADMIN).status_code == 422

    key = client.post("/devices", json={"name": "d"}, headers=ADMIN).json()["api_key"]
    now = datetime.now(UTC).replace(microsecond=0)
    body = {"readings": [{"metric": "temperature_c", "value": 40, "ts": now.isoformat()}]}
    client.post("/readings/batch", json=body, headers={"X-API-Key": key})
    with session_factory() as s:
        process_batch(s)

    open_alerts = client.get("/alerts", params={"status": "open"}, headers=ADMIN).json()
    assert [a["trigger_value"] for a in open_alerts] == [40]
    assert client.get("/alerts", params={"status": "resolved"}, headers=ADMIN).json() == []
