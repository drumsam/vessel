"""Permitted batch-feed adapter; remote transport and licensing stay source-specific."""
import json
from pathlib import Path
from ..observations.models import Candidate


class StructuredFeed:
    def __init__(self, source_id, path):
        self.source_id = source_id
        self.path = Path(path)

    def collect(self, unit):
        # Feed producers filter by requested canonical unit. Resolver remains authoritative.
        with self.path.open(encoding="utf-8") as stream:
            for line in stream:
                if line.strip():
                    payload = json.loads(line)
                    yield Candidate(**payload)
