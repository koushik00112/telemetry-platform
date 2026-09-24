"""Alert worker: polls for unchecked readings and evaluates alert rules.

Run with: python -m app.worker
"""

import logging
import signal
import threading
from types import FrameType

from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import sessionmaker

from app.db import get_engine
from app.services.alerts import process_batch

log = logging.getLogger("alert_worker")


def run(poll_interval: float = 1.0, batch_size: int = 500) -> None:
    stop = threading.Event()

    def handle_signal(signum: int, _frame: FrameType | None) -> None:
        log.info("received signal %s, finishing current batch", signum)
        stop.set()

    signal.signal(signal.SIGTERM, handle_signal)
    signal.signal(signal.SIGINT, handle_signal)

    factory = sessionmaker(bind=get_engine(), expire_on_commit=False)
    log.info("alert worker started")
    while not stop.is_set():
        processed = 0
        with factory() as session:
            try:
                processed = process_batch(session, batch_size)
            except IntegrityError:
                # Another worker opened the same alert first; the batch rolls back and is retried.
                session.rollback()
                log.warning("alert conflict with a concurrent worker, retrying batch")
                continue
            except OperationalError:
                session.rollback()
                log.exception("database unavailable, backing off")
                stop.wait(5)
                continue
        if processed:
            log.info("processed %d readings", processed)
        if processed < batch_size:
            stop.wait(poll_interval)
    log.info("alert worker stopped")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    run()
