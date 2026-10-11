"""Collector politeness: robots.txt is parsed per host, at runtime, every run.

No hardcoded allow list. If robots.txt cannot be read the collector does not
guess that fetching is fine: an unreadable robots.txt blocks the fetch, except
for a 404, which by convention means no restrictions.

`urllib.robotparser` is not used for the decision. It has no wildcard support:
`Disallow: /*page=*` is compared as a literal prefix, so it matches nothing and
every paginated URL reads as allowed. Lea & Sandeman, Lay & Wheeler Trading and
Bordeaux Index all write rules that way, so the rules are matched here instead,
with `*` and `$` as the de-facto standard defines them. Under-blocking is the
dangerous direction: it means fetching something a merchant asked us not to.

`Visit-time` is a real, if non-standard, field: Berry Bros. & Rudd's own
robots.txt (confirmed live, 10 October 2026) states `Visit-time:
0200-0700` — UTC, by the field's own convention — alongside `Crawl-delay:
10`. Nothing in `urllib.robotparser` or the de-facto standard this module
otherwise follows recognises it, so it would have been silently dropped
exactly like `Request-rate` already is, and the collector would have
fetched outside the one window a merchant asked to be visited in. Honoured
the same way `Crawl-delay` is: read per the matching user-agent group,
enforced in `check_robots`, refused rather than guessed at.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from urllib.parse import urlsplit

import httpx

from app.adapters.http import user_agent


class RobotsDisallowed(Exception):
    pass


def _groups(text: str) -> list[tuple[list[str], list[tuple[str, str]]]]:
    """[(user-agents, [(directive, value)])] — one entry per record."""
    groups: list[tuple[list[str], list[tuple[str, str]]]] = []
    agents: list[str] = []
    rules: list[tuple[str, str]] = []
    starting = True
    for raw_line in (text or "").splitlines():
        line = raw_line.split("#", 1)[0].strip()
        if not line or ":" not in line:
            continue
        field, _, value = line.partition(":")
        field, value = field.strip().lower(), value.strip()
        if field == "user-agent":
            if not starting:                      # a new record begins
                groups.append((agents, rules))
                agents, rules = [], []
            agents.append(value.lower())
            starting = True
        elif field in ("allow", "disallow", "crawl-delay", "visit-time"):
            starting = False
            rules.append((field, value))
    if agents or rules:
        groups.append((agents, rules))
    return groups


def _rules_for(text: str, ua: str) -> list[tuple[str, str]]:
    """The one group that applies to us: the most specific matching user-agent,
    or the `*` group. Never both — that is how robots.txt is defined."""
    token = ua.split("/")[0].strip().lower()
    best: list[tuple[str, str]] | None = None
    wildcard: list[tuple[str, str]] | None = None
    for agents, rules in _groups(text):
        for agent in agents:
            if agent == "*":
                wildcard = (wildcard or []) + rules
            elif agent and (agent in token or token.startswith(agent)):
                best = (best or []) + rules
    return best if best is not None else (wildcard or [])


def _matches(pattern: str, path: str) -> bool:
    """A robots path pattern, with `*` as any run of characters and a trailing
    `$` anchoring the end."""
    if pattern == "":
        return False
    anchored = pattern.endswith("$")
    body = pattern[:-1] if anchored else pattern
    regex = "".join(".*" if part == "*" else re.escape(part)
                    for part in re.split(r"(\*)", body))
    return re.match(regex + ("$" if anchored else ""), path) is not None


def allowed(text: str, url: str, ua: str) -> bool:
    """Longest matching rule wins; Allow wins a tie. Both are the de-facto
    standard, and both are what a merchant expects us to do."""
    parts = urlsplit(url)
    path = parts.path + (f"?{parts.query}" if parts.query else "")
    decision, strength = True, -1
    for field, value in _rules_for(text, ua):
        if field not in ("allow", "disallow") or not _matches(value, path):
            continue
        if len(value) > strength or (len(value) == strength and field == "allow"):
            decision, strength = field == "allow", len(value)
    return decision


def crawl_delay(text: str, ua: str) -> float:
    """Seconds a merchant asks us to wait between requests, or 0."""
    for field, value in _rules_for(text, ua):
        if field == "crawl-delay":
            try:
                return max(0.0, float(value))
            except ValueError:
                return 0.0
    return 0.0


_VISIT_TIME = re.compile(r"^(\d{2})(\d{2})\s*-\s*(\d{2})(\d{2})$")


def visit_window(text: str, ua: str) -> tuple[int, int] | None:
    """(start, end) in minutes since UTC midnight, or None if unrestricted.

    "0200-0700" -> (120, 420). The field names no timezone because the
    convention has none but UTC; written down here rather than assumed
    silently, since getting it wrong either direction fetches outside the
    one window a merchant asked for.
    """
    for field, value in _rules_for(text, ua):
        if field == "visit-time":
            m = _VISIT_TIME.match(value)
            if m:
                h1, m1, h2, m2 = (int(g) for g in m.groups())
                return (h1 * 60 + m1, h2 * 60 + m2)
    return None


def within_visit_window(text: str, ua: str, now: datetime) -> bool:
    """True when unrestricted, or `now` (UTC) falls inside the stated window.
    A window that wraps midnight (e.g. "2200-0600") is handled the same way
    Crawl-delay's own arithmetic is: read plainly, not assumed same-day."""
    window = visit_window(text, ua)
    if window is None:
        return True
    start, end = window
    minutes = now.hour * 60 + now.minute
    if start <= end:
        return start <= minutes <= end
    return minutes >= start or minutes <= end


def check_robots(url: str, ua: str | None = None, *, client: httpx.Client | None = None,
                 now: datetime | None = None) -> None:
    """Raise RobotsDisallowed unless robots.txt for this host permits `url`
    right now — both the path rules and, where stated, the visit-time window."""
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

    if not allowed(r.text, url, ua):
        raise RobotsDisallowed(f"robots.txt disallows {url} for {ua!r}")

    if not within_visit_window(r.text, ua, now or datetime.now(timezone.utc)):
        start, end = visit_window(r.text, ua)
        raise RobotsDisallowed(
            f"{robots_url} restricts visits to {start // 60:02d}{start % 60:02d}-"
            f"{end // 60:02d}{end % 60:02d} UTC for {ua!r}; now is outside that window")
