"""Run the background worker:  python -m app.worker"""
from __future__ import annotations

from rq import Worker

from app.worker.queue import QUEUE_NAME, redis_connection


def main() -> None:
    Worker([QUEUE_NAME], connection=redis_connection()).work()


if __name__ == "__main__":
    main()
