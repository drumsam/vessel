"""Collector politeness: robots.txt is parsed per host, at runtime, every run.

No hardcoded allow list. If robots.txt cannot be read the collector does not
guess that fetching is fine: an unreadable robots.txt blocks the fetch, except
for a 404, which by convention means no restrictions.
"""
from __future__ import annotations

from urllib.parse import urlsplit
from urllib.robotparser import RobotFileParser

import httpx

from app.adapters.http import user_agent


class RobotsDisallowed(Exception):
    pass


def check_robots(url: str, ua: str | None = None, *, client: httpx.Client | None = None) -> None:
    """Raise RobotsDisallowed unless robots.txt for this host permits `url`."""
    ua = ua or user_agent()
    parts = urlsplit(url)
    robots_url = f"{parts.scheme}://{parts.netloc}/robots.txt"
    http = client or httpx.Client(timeout=30, headers={"User-Agent": ua})
    try:
        r = http.get(robots_url)
    except httpx.HTTPError as e:
        raise RobotsDisallowed(f"{robots_url} unreadable: {e}") from e
    finally:
        if client is None:
            http.close()

    if r.status_code == 404:
        return
    if r.status_code != 200:
        raise RobotsDisallowed(f"{robots_url} returned HTTP {r.status_code}")

    rp = RobotFileParser()
    rp.parse(r.text.splitlines())
    if not rp.can_fetch(ua, url):
        raise RobotsDisallowed(f"robots.txt disallows {url} for {ua!r}")
