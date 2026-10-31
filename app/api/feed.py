"""POST /market-evidence/batches — source-agnostic market-evidence import
(decision 0048). Any provider that can produce the structured batch shape in
app/feed/importer.py posts here; acquisition is not this app's concern.

Authenticated by one narrow bearer token (MARKET_FEED_TOKEN, set on the
hosting platform), never an operator session: the token can write market
evidence and nothing else — no deal, no price, no operator data. Unset, the
route answers 503 rather than accepting anything.
"""
from __future__ import annotations

import hmac
import os
from typing import Optional

from fastapi import APIRouter, Body, Depends, Header, HTTPException

from app.db.connection import transaction
from app.feed import importer

router = APIRouter(tags=["market-evidence"])

#: A shorter secret is a configuration error, refused rather than trusted.
MIN_TOKEN_LENGTH = 32


def require_feed_token(authorization: Optional[str] = Header(default=None)) -> None:
    expected = os.environ.get("MARKET_FEED_TOKEN", "")
    if len(expected) < MIN_TOKEN_LENGTH:
        raise HTTPException(503, "market-evidence import is not configured")
    given = authorization[len("Bearer "):] if authorization and authorization.startswith("Bearer ") else ""
    if not given or not hmac.compare_digest(given.encode(), expected.encode()):
        raise HTTPException(401, "a valid market-feed token is required",
                            headers={"WWW-Authenticate": "Bearer"})


@router.post("/market-evidence/batches", dependencies=[Depends(require_feed_token)])
def import_market_evidence(batch: dict = Body(...)) -> dict:
    """One batch, all or nothing at the database level: a batch either lands
    whole (its bad observations as retained rejects) or not at all."""
    try:
        with transaction() as conn:
            return importer.import_batch(conn, batch)
    except importer.InvalidBatch as e:
        raise HTTPException(422, str(e))
