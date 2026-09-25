import threading
import time
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import sessionmaker

from app import worker
from app.models import Alert, AlertRule, Base, Device, Operator, Reading


@pytest.fixture
def session_factory(tmp_path):
    # The worker runs in its own thread, so it needs its own DB connection, as in
    # production. The in-memory StaticPool database in conftest shares one connection
    # across threads, where one thread's rollback can undo the other's writes.
    eng = create_engine(f"sqlite:///{tmp_path / 'worker.db'}", connect_args={"timeout": 10})
    Base.metadata.create_all(eng)
    return sessionmaker(bind=eng, expire_on_commit=False)


@pytest.fixture
def engine(session_factory, monkeypatch):
    eng = session_factory.kw["bind"]
    monkeypatch.setattr(worker, "get_engine", lambda: eng)
    return eng


def start(**kwargs):
    stop = threading.Event()
    t = threading.Thread(target=worker.run, kwargs={"stop": stop, **kwargs}, daemon=True)
    t.start()
    return stop, t


def wait_for(cond, timeout=5.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if cond():
            return True
        time.sleep(0.02)
    return False


def test_worker_drains_backlog_opens_alerts_and_stops_cleanly(engine, session_factory):
    with session_factory() as s:
        d = Device(id=uuid.uuid4(), name="d", api_key_hash="h")
        s.add_all([d, AlertRule(metric="t", operator=Operator.gt, threshold=10)])
        t0 = datetime(2026, 9, 28, tzinfo=UTC)
        s.add_all(
            Reading(device_id=d.id, metric="t", value=v, ts=t0 + timedelta(seconds=i))
            for i, v in enumerate([1, 50, 2] * 5)
        )
        s.commit()

    stop, thread = start(poll_interval=0.01, batch_size=4)

    def done():
        with session_factory() as s:
            return s.query(Reading).filter(Reading.alert_checked.is_(False)).count() == 0

    assert wait_for(done)
    stop.set()
    thread.join(timeout=2)
    assert not thread.is_alive()
    with session_factory() as s:
        assert s.query(Alert).count() == 5  # each 50 opens one, each following 2 resolves it


@pytest.mark.parametrize(
    "error",
    [
        IntegrityError("INSERT", {}, Exception("dup")),
        OperationalError("SELECT", {}, Exception("down")),
    ],
)
def test_worker_survives_db_errors_and_keeps_going(engine, monkeypatch, error):
    calls = []

    def flaky(session, batch_size):
        calls.append(1)
        if len(calls) == 1:
            raise error
        return 0

    monkeypatch.setattr(worker, "process_batch", flaky)
    stop, thread = start(poll_interval=0.01, backoff_seconds=0.01)
    assert wait_for(lambda: len(calls) >= 3)
    stop.set()
    thread.join(timeout=2)
    assert not thread.is_alive()


def test_signal_handler_sets_stop():
    import signal

    stop = threading.Event()
    previous = signal.getsignal(signal.SIGTERM)
    try:
        worker.install_signal_handlers(stop)
        signal.raise_signal(signal.SIGTERM)
        assert stop.is_set()
    finally:
        signal.signal(signal.SIGTERM, previous)
        signal.signal(signal.SIGINT, signal.default_int_handler)
