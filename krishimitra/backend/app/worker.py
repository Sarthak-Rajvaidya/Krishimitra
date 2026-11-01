"""Background worker:  python -m app.worker
Runs the periodic jobs the API must never do inside a request. Run ONE replica (the jobs are idempotent, but there is no leader election).
"""
import logging
import signal
import time
from datetime import timedelta

from app.core.logging import setup_logging
from app.db.base import utcnow
from app.db.session import SessionLocal

log = logging.getLogger("worker")
_stop = False


def _job(name, fn, *a):
    try:
        with SessionLocal() as db:
            r = fn(db, *a)
        if r:
            log.info("%s -> %s", name, r)
    except Exception as e:  # one failing job must not stop the others
        log.error("job %s failed: %s", name, type(e).__name__)


def main() -> None:
    setup_logging()
    from app.services import advisory_job, iot, notify

    signal.signal(signal.SIGTERM, lambda *_: globals().__setitem__("_stop", True))
    signal.signal(signal.SIGINT, lambda *_: globals().__setitem__("_stop", True))
    # name, function, every N seconds
    jobs = [("outbox", notify.process_outbox, 10), ("schedules", iot.run_schedules, 60), ("expire_commands", iot.expire_commands, 30),
            ("offline", iot.mark_offline, 120), ("rollup", iot.rollup_hourly, 900), ("advisory", advisory_job.run, 6 * 3600),
            ("purge_raw", iot.purge_raw, 24 * 3600)]
    last = {n: utcnow() - timedelta(days=1) for n, _, _ in jobs}
    log.info("worker started")
    while not _stop:
        now = utcnow()
        for name, fn, every in jobs:
            if (now - last[name]).total_seconds() >= every:
                last[name] = now
                _job(name, fn)
        time.sleep(2)
    log.info("worker stopped")


if __name__ == "__main__":
    main()
