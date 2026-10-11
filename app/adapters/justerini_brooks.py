"""Justerini & Brooks — server-rendered Next.js, confirmed live 10 October 2026.

Investigated for UK breadth (Doug, 10 October 2026, after the Champagne sweep
left 42 of 52 targets at one merchant or none): "The design needs 3+ sources
to mean anything." First of three houses, built one at a time.

robots.txt allows everything this adapter touches (`Allow: /*`, a handful of
account/API paths disallowed, none of them product pages); no Crawl-delay, no
Visit-time. Politeness here is self-imposed pacing between requests, same
discipline as everywhere else in this fleet.

## The data is real, but it is not in the HTML a human reads

Each product-family page (`/fine-wines/france/champagne/<producer>/
<family>`) is a Next.js App Router page whose content arrives as React
Server Component "flight" data: `self.__next_f.push([1, "<chunk-id>:
<payload>"])` calls scattered through the page, one chunk id reused across
several calls when a payload is split. `extract_listings()` reassembles
them by id, parses each as JSON where it parses at all (most chunks are
import references or UI tree fragments, not data, and are skipped rather
than treated as an error), and walks the result for every dict carrying
`bottlePriceExcTaxes` — pruning any subtree reached through a
`relatedProducts` key, which is cross-sell for OTHER products the page
also renders and is not this family's own stock.

## The family page shows every edition or vintage currently stocked, not just the one named in the URL

`/krug/krug-grande-cuvee-edition/169TH` and `/krug/krug-grande-cuvee-edition`
(no suffix) return the same underlying stock table — the suffix only
presets which variant the page highlights. One fetch per family, `vintage`
ignored, same reasoning as the LiveTrade adapter's own free-text search:
every edition the family covers comes back together, and each is screened
on its own vintage/release_code downstream.

## Three stock types, read differently

- `RT` ("Portfolio Wines") — J&B's own held stock. A real ASK.
- `EP` ("En Primeur Wines") — a firm, priced, future-delivery position, not
  a speculative indication: `vatStatusIncTaxes` reads "Ex Duty & VAT" here
  too (there is no duty-paid price yet to show), consistent with a wine
  that has not been shipped, not with an unconfirmed quote. Also an ASK.
- `BR` ("Broking Wines") — sourced through J&B's broking desk rather than
  held in its own portfolio. Treated as `PriceKind.INDICATION` /
  `StockType.BROKERED`, the same conservative read this codebase already
  gives FINE+RARE's aggregated indications (decision 0013): the page shows
  a specific quantity and price, which reads more confirmed than FINE+RARE's
  own `quantity: 0` convention, but nothing on the page distinguishes a firm
  broked order from a quote J&B believes it can source — and a wrong Floor
  from an unconfirmed broker quote is a worse failure than under-counting
  depth by one source. Revisit if J&B's own terms say otherwise.

## In Bond is the ExcTaxes price, not a separate row

Unlike Bordeaux Index (duty-paid nested as its own row) or LW Trading (a
Duty Status attribute), J&B publishes ONE listing with TWO price fields —
`bottlePriceExcTaxes`/`casePriceExcTaxes` (Ex Duty & VAT — In Bond) and
`bottlePriceIncTaxes`/`casePriceIncTaxes` (Inc Duty & VAT — duty paid,
landed) — for the same stock position. Only the ExcTaxes figure is ever
read; the IncTaxes figure is never emitted as a second, separate offer.

## `familyName` is not reliably producer-first

Bordeaux Index's title is always "producer, cuvee". J&B's `familyName` is
NOT: "Dom Pérignon, Rosé" and "Taittinger, Blanc de Blancs, Comtes de
Champagne" lead with the producer, but "Cristal, Brut", "Cuvée Sir
Winston Churchill, Brut" and "Les Chetillons, Le Mesnil, Grand Cru" do
not — confirmed live across all eleven producers this adapter was built
against. Guessing which pattern applies per producer would be exactly the
kind of invented identity split CLAUDE.md refuses, so the producer is
never read from the page at all: the CALLER already knows it (it chose
which family path to fetch, from the merchant's own sitemap, never
guessed), and passes it alongside each path. `cuvee_text` is `familyName`
with that producer name stripped as a leading comma-segment ONLY when it
actually matches; otherwise `familyName` is kept whole, so a mismatch
degrades to an unresolved identity rather than a silently wrong split.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from decimal import Decimal
from typing import Sequence

from app.core.enums import DutyStatus, PriceKind, Reject, StockType
from app.core.models import Offer
from app.identity.resolver import norm_producer, split_release_code
from .base import Adapter, Candidate, Rejected
from .http import user_agent

BASE = "https://www.justerinis.com"

#: Next.js RSC flight data: self.__next_f.push([1, "<chunk-id>:<payload>"]).
_PUSH_RE = re.compile(r'self\.__next_f\.push\(\[1,("(?:[^"\\]|\\.)*")\]\)')

#: "6x75cl" / "1x1.5L" / "3x1.5L" -> (pack_size, bottle_ml).
_MEASURE_RE = re.compile(r"^(\d+)x([\d.]+)(cl|L)$")

#: A release code read off the ordinal suffix J&B's own `vintageName` already
#: carries clean, separate from the cuvee string entirely: "167TH" -> "167".
#: Nothing here is guessed from merchant prose the way split_release_code
#: reads Bordeaux Index's title — this field IS the parsed answer already.
_LEADING_DIGITS_RE = re.compile(r"^(\d+)")

_STOCK_TYPE = {
    "RT": (PriceKind.ASK, StockType.MERCHANT_STOCK),
    "EP": (PriceKind.ASK, StockType.MERCHANT_STOCK),
    "BR": (PriceKind.INDICATION, StockType.BROKERED),
}


def _chunks_of(html: str) -> dict[str, str]:
    """{chunk id: concatenated payload}. A chunk id is reused across several
    push calls when its payload is split; concatenation order is push order,
    which is document order, which is the only order that is ever correct."""
    chunks: dict[str, str] = {}
    for m in _PUSH_RE.finditer(html or ""):
        s = json.loads(m.group(1))
        idx = s.find(":")
        if idx < 0:
            continue
        cid, payload = s[:idx], s[idx + 1:]
        chunks[cid] = chunks.get(cid, "") + payload
    return chunks


def extract_listings(html: str) -> list[dict]:  # pragma: no cover - thin DOM shim
    """Every stock listing on the page, for THIS product family only.

    Most chunks are not JSON at all (import references, UI tree fragments)
    and are skipped the moment json.loads refuses them — that is normal,
    not an error, for this format. `relatedProducts` is pruned unconditionally:
    it is cross-sell for a DIFFERENT product the same page renders, never
    this family's own stock.
    """
    out: list[dict] = []

    def walk(x):
        if isinstance(x, dict):
            if "bottlePriceExcTaxes" in x:
                out.append(x)
                return
            for k, v in x.items():
                if k == "relatedProducts":
                    continue
                walk(v)
        elif isinstance(x, list):
            for v in x:
                walk(v)

    for payload in _chunks_of(html).values():
        try:
            data = json.loads(payload)
        except ValueError:
            continue
        walk(data)
    return out


def parse_measure(text: str) -> tuple[int, int] | None:
    """"6x75cl" -> (6, 750). "1x1.5L" -> (1, 1500). None if unreadable."""
    m = _MEASURE_RE.match((text or "").strip())
    if not m:
        return None
    pack = int(m.group(1))
    value = float(m.group(2))
    factor = 10 if m.group(3) == "cl" else 1000
    ml = round(value * factor)
    return (pack, ml) if pack >= 1 and ml > 0 else None


def parse_vintage_name(vintage_name: str) -> tuple[int, str | None] | None:
    """"2015" -> (2015, None), real vintage. "167TH" -> (1000, "167"), an NV
    edition. "NV" or "" -> (1000, None), plain NV. None if unreadable — fails
    closed rather than guessing a vintage out of something unexpected.
    """
    text = (vintage_name or "").strip()
    if text.isdigit() and len(text) == 4:
        return int(text), None
    if text.upper() in ("NV", "N.V.", ""):
        return 1000, None
    m = _LEADING_DIGITS_RE.match(text)
    return (1000, m.group(1)) if m else None


class JusteriniBrooksAdapter(Adapter):
    id = "justerini-brooks"
    merchant = "Justerini & Brooks"

    def fetch(self, producer_paths: Sequence[tuple[str, str]], vintage: int | None = None, *,
              client=None) -> Sequence[dict]:
        """One or more (producer display name, family path) pairs, each
        verified against the merchant's own product sitemap, never guessed —
        a producer can publish the same cuvee under two different family
        slugs (Pol Roger's "cuvee-sir-winston-churchill" and "...-brut",
        confirmed live), and those are fetched and unioned the same way
        Bordeaux Index's own slug union works. `vintage` is accepted only to
        match the shared `(adapter, params, vintage)` call shape
        (`app.worker.jobs.TARGETED`) — every edition or vintage a family page
        currently stocks comes back in one fetch, same reasoning as the
        LiveTrade adapter's free-text search.
        """
        if not producer_paths:
            raise ValueError("at least one (producer, path) pair is required")
        owns_client = client is None
        if owns_client:  # pragma: no cover - network
            import httpx
            client = httpx.Client(timeout=30, follow_redirects=True,
                                  headers={"User-Agent": user_agent()})
        try:
            out: list[dict] = []
            for producer, path in producer_paths:
                r = client.get(BASE + path)
                if r.status_code == 404:
                    continue
                r.raise_for_status()
                for item in extract_listings(r.text):
                    out.append({**item, "_producer": producer, "_path": path})
            return out
        finally:
            if owns_client:  # pragma: no cover - network
                client.close()

    def normalise(self, raw: dict, captured_at: datetime | None = None):
        """Up to TWO candidates per listing. `stockBottles` and `stockCases`
        are separate pools, not one count read two ways — confirmed live:
        Taittinger Rosé Comtes de Champagne 2009 shows 2 loose bottles AND 6
        cases of the SAME listing at once. A case-measure listing (say
        "6x75cl") with bottles in stock is quietly also an offer at 1x75cl,
        the seller's own unit for a loose-bottle cellar — the one commercial
        unit this whole sweep otherwise keeps missing. Both are emitted,
        never just the headline case; neither is emitted when its own pool
        reads zero.
        """
        producer = raw.get("_producer") or ""
        family_name = raw.get("familyName") or ""
        if not producer or not family_name:
            return Rejected(raw, Reject.UNRESOLVED_IDENTITY,
                            f"no producer/familyName on {raw.get('uniqueId')!r}")

        # familyName is producer-first ONLY sometimes (see module docstring) —
        # strip the producer only when it is actually there, by normalised
        # text, never by position alone.
        head, comma, rest = family_name.partition(",")
        cuvee = rest.strip() if comma and norm_producer(head) == norm_producer(producer) \
            else family_name.strip()

        parsed_vintage = parse_vintage_name(raw.get("vintageName"))
        if parsed_vintage is None:
            return Rejected(raw, Reject.VINTAGE,
                            f"unreadable vintageName {raw.get('vintageName')!r}")
        vintage, release_code = parsed_vintage
        if release_code:
            # "Grande Cuvée, Edition" with its own release code already known
            # from vintageName — the trailing descriptor is redundant, not a
            # second identity signal, and split_release_code would not catch
            # it anyway (the number is not in this string at all).
            cuvee = re.sub(r",?\s*[EÉ]dition\s*$", "", cuvee, flags=re.IGNORECASE).strip()

        size = parse_measure(raw.get("measureName"))
        if size is None:
            return Rejected(raw, Reject.SIZE, f"unreadable measureName {raw.get('measureName')!r}")
        pack_size, bottle_ml = size

        price_kind, stock_type = _STOCK_TYPE.get(raw.get("stockType"), (None, None))
        if price_kind is None:
            return Rejected(raw, Reject.UNRESOLVED_IDENTITY,
                            f"unknown stockType {raw.get('stockType')!r}")

        item_code = raw.get("uniqueId")
        source_url = BASE + (raw.get("_path") or raw.get("familyUrlSlug") or "")
        when = captured_at or datetime.now(timezone.utc)

        def offer(suffix: str, price, pack: int, ml: int, units) -> Offer:
            return Offer(
                offer_id=f"jb:{item_code}:{suffix}",
                merchant_id=self.id, merchant=self.merchant,
                wine_id="", vintage=vintage, bottle_ml=ml, pack_size=pack,
                price=Decimal(str(price)), currency="GBP",   # UK-domestic; no currency field published
                duty_status=DutyStatus.IN_BOND,               # ExcTaxes is always "Ex Duty & VAT"
                price_kind=price_kind, is_buyable=bool(units and units > 0),
                offered_units=units, stock_type=stock_type, stock_type_basis="declared",
                condition_flags=frozenset(), condition_notes=None,   # no condition field published
                source_url=source_url, captured_at=when, raw=raw)

        out: list[Candidate | Rejected] = []
        case_price, case_units = raw.get("casePriceExcTaxes"), raw.get("stockCases")
        if case_price and case_price > 0:
            out.append(Candidate(offer=offer("case", case_price, pack_size, bottle_ml, case_units),
                                 producer_text=producer, cuvee_text=cuvee, release_code=release_code))

        if pack_size > 1:
            bottle_price, bottle_units = raw.get("bottlePriceExcTaxes"), raw.get("stockBottles")
            if bottle_price and bottle_price > 0:
                out.append(Candidate(offer=offer("bottle", bottle_price, 1, bottle_ml, bottle_units),
                                     producer_text=producer, cuvee_text=cuvee, release_code=release_code))

        if not out:
            return Rejected(raw, Reject.NON_POSITIVE_PRICE,
                            f"item {item_code!r}: no usable case or bottle price")
        return out
