"""Run the background worker:  python -m app.worker

RQ's default worker forks a work-horse per job, which is what you want in
production: a job that segfaults cannot take the worker with it.

On macOS that fork is unsafe for any job that touches TLS. The parent has
already initialised Apple's Objective-C runtime (httpx -> ssl -> Security
framework), and the forked child aborts with

    objc[...]: +[NSNumber initialize] may have been in progress in another
    thread when fork() was called. ... Crashing instead.

which RQ reports as "Work-horse terminated unexpectedly ... signal 6". The
collection jobs are exactly the ones that fetch over HTTPS, so on macOS set

    RQ_WORKER_CLASS=simple      # runs jobs in-process, no fork

Linux is unaffected; leave it alone there.
"""
from __future__ import annotations

import os

from rq import SimpleWorker, Worker

from app.worker.queue import QUEUE_NAME, redis_connection

WORKER_CLASSES = {"fork": Worker, "simple": SimpleWorker}


def main() -> None:
    name = os.environ.get("RQ_WORKER_CLASS", "fork").lower()
    if name not in WORKER_CLASSES:
        raise SystemExit(f"RQ_WORKER_CLASS must be one of {sorted(WORKER_CLASSES)}, not {name!r}")
    WORKER_CLASSES[name]([QUEUE_NAME], connection=redis_connection()).work()


if __name__ == "__main__":
    main()
