"""Alert worker: polls for unchecked readings and evaluates alert rules.

Run with: python -m app.worker   (Prometheus metrics on :9100/metrics)
"""

import logging
import os
import signal
import threading
import time
from types import FrameType

from prometheus_client import start_http_server
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import sessionmaker

from app.config import get_settings
from app.db import get_engine
from app.log import configure_logging
from app.metrics import WORKER_BACKLOG, WORKER_BATCH_SECONDS, WORKER_PROCESSED
from app.services.alerts import backlog, process_batch

log = logging.getLogger("alert_worker")


def run(
    poll_interval: float = 1.0,
    batch_size: int = 500,
    stop: threading.Event | None = None,
    backoff_seconds: float = 5.0,
) -> None:
    """Loop until stopped. Pass `stop` to control it from another thread (tests)."""
    if stop is None:
        stop = threading.Event()
        install_signal_handlers(stop)

    factory = sessionmaker(bind=get_engine(), expire_on_commit=False)
    log.info("alert worker started")
    while not stop.is_set():
        processed = 0
        started = time.perf_counter()
        with factory() as session:
            try:
                processed = process_batch(session, batch_size)
                WORKER_BACKLOG.set(backlog(session))
            except IntegrityError:
                # Another worker opened the same alert first; the batch rolls back and is retried.
                session.rollback()
                log.warning("alert conflict with a concurrent worker, retrying batch")
                stop.wait(0.1)
                continue
            except OperationalError:
                session.rollback()
                log.exception("database unavailable, backing off")
                stop.wait(backoff_seconds)
                continue
        if processed:
            WORKER_PROCESSED.inc(processed)
            WORKER_BATCH_SECONDS.observe(time.perf_counter() - started)
            log.info("processed batch", extra={"readings": processed})
        if processed < batch_size:
            stop.wait(poll_interval)
    log.info("alert worker stopped")


def install_signal_handlers(stop: threading.Event) -> None:
    def handle_signal(signum: int, _frame: FrameType | None) -> None:
        log.info("received signal, finishing current batch", extra={"signal": signum})
        stop.set()

    signal.signal(signal.SIGTERM, handle_signal)
    signal.signal(signal.SIGINT, handle_signal)


if __name__ == "__main__":
    settings = get_settings()
    configure_logging(settings.log_level, settings.log_json)
    start_http_server(int(os.environ.get("METRICS_PORT", "9100")))
    run()
