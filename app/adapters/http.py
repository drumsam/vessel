"""The collector's one User-Agent.

Every adapter and the robots.txt check read it from here. There is no default:
an honest, identifiable User-Agent with a contact URL is operator configuration,
and a hardcoded placeholder would be neither honest nor identifiable.
"""
from __future__ import annotations

import os


def user_agent() -> str:
    ua = os.environ.get("COLLECTOR_USER_AGENT", "").strip()
    if not ua:
        raise RuntimeError(
            "COLLECTOR_USER_AGENT is not set. It must identify this collector and "
            "give a contact URL, e.g. 'UKFineWinePricer/1.0 (+https://your.site/contact)'.")
    return ua
