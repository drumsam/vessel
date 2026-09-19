"""The single RQ queue. Redis connection comes from REDIS_URL."""
from __future__ import annotations

import os

from redis import Redis
from rq import Queue

QUEUE_NAME = "pricer"


def redis_connection() -> Redis:
    url = os.environ.get("REDIS_URL")
    if not url:
        raise RuntimeError("REDIS_URL is not set")
    return Redis.from_url(url)


def get_queue(connection: Redis | None = None) -> Queue:
    return Queue(QUEUE_NAME, connection=connection or redis_connection())
