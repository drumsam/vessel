"""Background jobs. Each is a plain function with structured input and output.

RQ imports these by dotted path, so every job takes only ids and simple
values and opens its own database connection.

    SNAPSHOT LOOKUP ......... collect_snapshot  (whole-book merchant feeds)
    DEEP MERCHANT SEARCH .... deep_search       (the gaps, per producer + vintage)
                              collect_targeted  (one producer + vintage)
    DETERMINISTIC BENCHMARK . benchmark_deal
    VINTAGE-BAND CHECK ...... inside benchmark_deal, and reinstate_comp to undo it
    PRICING ................. price_deal
    RETENTION ............... prune_snapshots
"""
from __future__ import annotations

import os
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from decimal import Decimal
from typing import Callable, Iterable, Optional, Sequence

import psycopg

from app.adapters.base import Adapter, Candidate, Rejected, whole_pence
from app.adapters.bordeaux_index import LIST_URL as BI_URL, BordeauxIndexAdapter
from app.adapters.farr import FEED_URL as FARR_URL, FarrAdapter
from app.adapters.fine_and_rare import (
    PRODUCER_INDEX_URL as FRW_URL, FineAndRareAdapter)
from app.adapters.goedhuis import PRODUCTS_URL as GOEDHUIS_URL, GoedhuisAdapter
from app.adapters.lea_sandeman import LIST_URL as LS_URL, LeaSandemanAdapter
from app.adapters.lw_trading import API_URL as LW_URL, LayWheelerTradingAdapter
from app.core.benchmark import benchmark
from app.core.enums import Reject
from app.core.models import Offer
from app.db import repo
from app.db.connection import transaction
from app.identity.resolver import collided_lwins, norm_producer
from app.market.units import case_pairs, derivation_allowed
from app.market.vintage_band import (
    band_flags, check_vintage_band, without_high_outliers)
from app.pricing.pricer import DEEP_DISCOUNT_THRESHOLD, CannotPrice, price_line
from app.worker.politeness import check_robots

#: Bumped when the adapter output contract changes shape.
SNAPSHOT_SCHEMA_VERSION = "2"

#: Ingest-level rejection reasons. They are about the record as a whole, not a
#: pricing screen, so they are not members of app.core.enums.Reject.
NOT_WHOLE_PENCE = "NOT_WHOLE_PENCE"
NO_OFFER_ROWS = "NO_OFFER_ROWS"


@dataclass(frozen=True)
class WholeBook:
    """A merchant whose adapter fetches its entire offer book in one call."""
    adapter: Callable[[], Adapter]
    robots_url: str


@dataclass(frozen=True)
class Targeted:
    """A merchant that can only be searched by producer and vintage.

    `params` names the merchant-specific search terms, one of which the caller
    must supply: a producer may be listed under more than one slug, and those
    are searched together. `call` turns those terms into that merchant's own
    fetch, because each merchant asks the question its own way.
    """
    adapter: Callable[[], Adapter]
    robots_url: str
    params: tuple[str, ...]
    call: Callable[[Adapter, dict, int], Sequence[dict]]


WHOLE_BOOK: dict[str, WholeBook] = {
    "farr": WholeBook(FarrAdapter, FARR_URL),
    "goedhuis": WholeBook(GoedhuisAdapter, GOEDHUIS_URL),
}

SLUG_PARAMS = ("producer_slug", "producer_slugs")


def _by_slug(adapter: Adapter, params: dict, vintage: int) -> Sequence[dict]:
    return adapter.fetch(params.get("producer_slug"), vintage,
                         producer_slugs=params.get("producer_slugs"))


def _by_search(adapter: Adapter, params: dict, vintage: int) -> Sequence[dict]:
    return adapter.fetch(params.get("search") or params.get("producer_slug"), vintage)


WHOLE_BOOK["lea-sandeman"] = WholeBook(LeaSandemanAdapter, LS_URL)

TARGETED: dict[str, Targeted] = {
    "bordeaux-index": Targeted(BordeauxIndexAdapter, BI_URL, SLUG_PARAMS, _by_slug),
    # A brokerage: what it publishes is an indication, not stock (decision 0013).
    "fine-rare": Targeted(FineAndRareAdapter, FRW_URL, SLUG_PARAMS, _by_slug),
    # Searched by producer term; robots asks for ten seconds between requests.
    "lw-trading": Targeted(LayWheelerTradingAdapter, LW_URL,
                           ("search",) + SLUG_PARAMS, _by_search),
}


def _now() -> datetime:
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------- collection


def _outputs(adapter: Adapter, raw: dict, captured_at: datetime) -> list[Candidate | Rejected]:
    out = adapter.normalise(raw, captured_at=captured_at)
    return out if isinstance(out, list) else [out]


def ingest(conn: psycopg.Connection, snapshot_id: str, adapter: Adapter,
           records: Iterable[dict], captured_at: datetime,
           registry=None) -> tuple[int, int]:
    """Normalise, resolve identity, persist. Returns (written, rejected).

    Every raw record ends as at least one `offer` or `offer_reject` row: a
    Bordeaux Index card with no parsable offer row is itself a reject.
    A candidate whose identity cannot be approved is an UNRESOLVED_IDENTITY
    reject, never an offer (offer.wine_id is NOT NULL).
    """
    registry = registry or repo.load_registry(conn)
    normalised = [(raw, _outputs(adapter, raw, captured_at)) for raw in records]
    candidates = [c for _, outs in normalised for c in outs if isinstance(c, Candidate)]

    # An LWIN this merchant applies to two different names goes to the operator
    # queue: it may be the merchant's mapping error or our name key splitting one
    # wine (decision 0006). Until an operator says otherwise it still
    # cross-checks, so a record it contradicts stays unresolved rather than
    # being priced. LWINs already judged unreliable are skipped entirely.
    collisions = collided_lwins([(c.lwin7, c.producer_text, c.cuvee_text) for c in candidates])
    repo.record_lwin_conflicts(conn, adapter.id, collisions)
    untrusted = repo.untrusted_lwins(conn, adapter.id)

    written = rejected = 0
    kept: list[Offer] = []
    for raw, outs in normalised:
        if not outs:
            repo.write_reject(conn, snapshot_id, adapter.id, NO_OFFER_ROWS,
                              "no offer row could be parsed", raw)
            rejected += 1
        for out in outs:
            if isinstance(out, Rejected):
                repo.write_reject(conn, snapshot_id, adapter.id, out.reason.name,
                                  out.detail, out.raw)
                rejected += 1
                continue
            if not whole_pence(out.offer.price):
                repo.write_reject(conn, snapshot_id, adapter.id, NOT_WHOLE_PENCE,
                                  f"price {out.offer.price} is not a whole number of pence",
                                  repo.unresolved_raw(out))
                rejected += 1
                continue
            lwin7 = None if out.lwin7 in untrusted else out.lwin7
            wine_id = registry.resolve_candidate(out.producer_text, out.cuvee_text, lwin7)
            if wine_id is None:
                detail = f"{out.producer_text!r} / {out.cuvee_text!r}"
                if out.lwin7:
                    detail += f" / LWIN-7 {out.lwin7}"
                    if out.lwin7 in untrusted:
                        detail += " (untrusted, not used)"
                    elif out.lwin7 in collisions:
                        detail += " (conflict open)"
                repo.write_reject(conn, snapshot_id, adapter.id,
                                  Reject.UNRESOLVED_IDENTITY.name, detail,
                                  repo.unresolved_raw(out))
                rejected += 1
                continue
            stored = replace(out.offer, wine_id=wine_id)
            repo.write_offer(conn, snapshot_id, stored)
            kept.append(stored)
            written += 1

    # A wine met in two pack sizes in ONE fetch is a paired same-day
    # observation, which is the only honest way to measure the case premium:
    # no assumption about timing or market drift. Recorded while the traffic is
    # happening anyway; nothing in the pricing path reads it (decision 0016).
    repo.record_case_pairs(conn, snapshot_id, adapter.id, case_pairs(kept), captured_at)
    return written, rejected


def _finish(snapshot_id: str, outcomes: list[dict]) -> None:
    with transaction() as conn:
        repo.finish_snapshot(
            conn, snapshot_id,
            attempted=len(outcomes),
            succeeded=sum(1 for o in outcomes if not o.get("error")),
            written=sum(o.get("written", 0) for o in outcomes),
            rejected=sum(o.get("rejected", 0) for o in outcomes),
            failures=[{"merchant_id": o["merchant_id"], "error": o["error"]}
                      for o in outcomes if o.get("error")])


def _capture(snapshot_id: str, merchant_id: str, adapter: Adapter, robots_url: str,
             fetch: Callable[[], Sequence[dict]], robots: Callable[[str], None],
             scope: dict) -> dict:
    """Fetch and ingest one merchant into its own transaction, stamped with its
    own capture time. A failure is recorded against that merchant only."""
    captured_at = _now()
    try:
        robots(robots_url)
        records = fetch()
        with transaction() as conn:
            written, rejected = ingest(conn, snapshot_id, adapter, records, captured_at)
            repo.write_snapshot_merchant(conn, snapshot_id, merchant_id,
                                         captured_at=captured_at, written=written,
                                         rejected=rejected, **scope)
        return {"merchant_id": merchant_id, "written": written, "rejected": rejected}
    except Exception as e:  # recorded, never swallowed silently
        error = f"{type(e).__name__}: {e}"
        with transaction() as conn:
            repo.write_snapshot_merchant(conn, snapshot_id, merchant_id,
                                         captured_at=captured_at, error=error, **scope)
        return {"merchant_id": merchant_id, "error": error}


def _approved(conn: psycopg.Connection) -> set[str]:
    return {m["merchant_id"] for m in repo.list_merchants(conn) if m["approved"]}


def collect_snapshot(merchant_ids: Optional[Sequence[str]] = None, *,
                     is_demo: bool = False,
                     fetch: Optional[Callable[[Adapter], Sequence[dict]]] = None,
                     robots: Callable[[str], None] = check_robots) -> str:
    """Fetch whole-book merchants into a new snapshot, one capture each.

    Benchmarks resolve each merchant's latest covering capture independently,
    so a snapshot need not hold every merchant.
    """
    wanted = list(merchant_ids) if merchant_ids else list(WHOLE_BOOK)
    fetch = fetch or (lambda a: a.fetch())
    with transaction() as conn:
        snapshot_id = repo.create_snapshot(conn, captured_at=_now(),
                                           schema_version=SNAPSHOT_SCHEMA_VERSION,
                                           is_demo=is_demo)
        approved = _approved(conn)

    outcomes = []
    for mid in wanted:
        if mid not in approved:
            outcomes.append({"merchant_id": mid, "error": "not an approved merchant"})
        elif mid in TARGETED:
            outcomes.append({"merchant_id": mid,
                             "error": "searched by producer and vintage: use collect_targeted"})
        elif mid not in WHOLE_BOOK:
            outcomes.append({"merchant_id": mid, "error": "no adapter"})
        else:
            spec = WHOLE_BOOK[mid]
            adapter = spec.adapter()
            outcomes.append(_capture(snapshot_id, mid, adapter, spec.robots_url,
                                     lambda: fetch(adapter), robots, {}))
    _finish(snapshot_id, outcomes)
    return str(snapshot_id)


def collect_targeted(merchant_id: str, wine_id: str, vintage: int, params: dict, *,
                     is_demo: bool = False,
                     fetch: Optional[Callable[[Adapter, dict, int], Sequence[dict]]] = None,
                     robots: Callable[[str], None] = check_robots) -> str:
    """Search one merchant for one producer and vintage (DEEP MERCHANT SEARCH).

    The capture's scope is that producer (as normalised in wine_key) and that
    vintage. It covers every wine of the producer in that vintage, and nothing
    else, when benchmarks resolve sources.
    """
    spec = TARGETED.get(merchant_id)
    if spec is None:
        raise ValueError(f"{merchant_id!r} has no targeted search")
    if not any(params.get(k) for k in spec.params):
        raise ValueError(f"{merchant_id} search needs one of {list(spec.params)}")
    fetch = fetch or (lambda a, p, v: spec.call(a, p, v))

    with transaction() as conn:
        wine = repo.get_wine(conn, wine_id)
        if wine is None:
            raise LookupError(f"wine {wine_id} not found")
        if merchant_id not in _approved(conn):
            raise ValueError(f"{merchant_id!r} is not an approved merchant")
        snapshot_id = repo.create_snapshot(conn, captured_at=_now(),
                                           schema_version=SNAPSHOT_SCHEMA_VERSION,
                                           is_demo=is_demo)

    adapter = spec.adapter()
    scope = {"scope_producer_key": repo.producer_key_of(wine), "scope_vintage": vintage,
             "scope_params": dict(params)}
    outcome = _capture(snapshot_id, merchant_id, adapter, spec.robots_url,
                       lambda: fetch(adapter, params, vintage), robots, scope)
    _finish(snapshot_id, [outcome])
    return str(snapshot_id)


# ----------------------------------------------------------------- benchmark


def benchmark_deal(deal_id: str, as_of: Optional[str] = None) -> dict:
    """Benchmark every line of a deal as of one instant (default: now).

    A line is skipped, not marked NO_MARKET, when its identity is unapproved or
    when no approved merchant has any capture covering it: in both cases nobody
    has looked, and NO_MARKET would claim that somebody did.
    """
    when = datetime.fromisoformat(as_of) if as_of else _now()
    runs, unapproved, no_coverage, excluded = {}, [], [], {}
    with transaction() as conn:
        if repo.get_deal(conn, deal_id) is None:
            raise LookupError(f"deal {deal_id} not found")
        for row in repo.deal_lines(conn, deal_id):
            line = repo.seller_line_for_benchmark(row)
            if line is None:
                unapproved.append(str(row["line_id"]))
                continue
            res = repo.resolve_offers(conn, wine_id=line.wine_id, vintage=line.vintage,
                                      as_of=when)
            if not res.sources:
                no_coverage.append(line.line_id)
                continue
            run_id, check = _benchmark_with_band(conn, line, res, when)
            runs[line.line_id] = run_id
            if check.high_outliers:
                excluded[line.line_id] = [ref.merchant for ref in check.high_outliers]
    return {"as_of": when.isoformat(), "runs": runs,
            "unapproved_identity": unapproved, "no_coverage": no_coverage,
            "comps_excluded_by_band": excluded}


def _benchmark_with_band(conn: psycopg.Connection, line, res: repo.Resolution,
                         when: datetime, *, wine_region: Optional[str] = None,
                         reinstated: Sequence[str] = ()) -> tuple[str, "object"]:
    """Benchmark, sanity-check the comps against their neighbouring vintages,
    and re-benchmark without any comp the band found too dear.

    The order matters: the band runs on comps the benchmark has already
    accepted, so it can never introduce one. `reinstated` names offers an
    operator has put back, which the band must not exclude a second time — the
    person has seen the number and overruled the rule.

    Neighbours and other formats come out of the same resolution the benchmark
    used. Nothing extra is fetched, and nothing here is ever a price.
    """
    region = (wine_region if wine_region is not None
              else repo.wine_register_key(conn, line.wine_id))
    # Whether this line may derive a comparable across case sizes is a fact
    # about the wine's region, which the core does not know (decision 0016).
    # It is decided here, once, before any benchmark runs.
    line = replace(line, derive_units=derivation_allowed(region))
    result = benchmark(line, res.offers, as_of=when)
    # Every comparable, not just the merchant-bests: Bordeaux Index lists the
    # 2020 Mugneret-Gibourg six-pack at £2,070 AND £2,074, and excluding only
    # the best of them promotes the other. The Reference would fall from £2,070
    # to £2,074 and the whole check would have achieved nothing.
    check = check_vintage_band(
        line, result.comparables,
        neighbour_offers=res.offers, other_format_offers=res.offers, as_of=when,
        tiers=repo.vintage_tiers(conn, region))
    if reinstated:
        check = replace(check, high_outliers=[ref for ref in check.high_outliers
                                              if ref.offer_id not in set(reinstated)])

    # Both band flags are review flags (decision 0015), carried into the run
    # through inherited_flags — the mechanism decision 0005 built for this. They
    # can hold a line in review and can never release one, so a line where a
    # dear comp was thrown out, or a cheap one looks wrong, always reaches a
    # person rather than depending on ONE_COMP to catch it.
    flags = band_flags(check)
    if flags or check.high_outliers:
        line = replace(line, inherited_flags=frozenset(line.inherited_flags) | flags)
        offers = without_high_outliers(res.offers, check) if check.high_outliers else res.offers
        result = benchmark(line, offers, as_of=when)

    run_id = str(repo.save_benchmark(conn, result, res, region=region))
    repo.save_vintage_band(conn, run_id, check, res)
    return run_id, check


def reinstate_comp(exclusion_id: str, reinstated_by: str, reason: str) -> dict:
    """Put an automatically excluded comp back, and say who did it.

    "One-click put it back" (spec 5). The original run is never edited: a new
    run is computed with the comp restored, and the exclusion row records who
    asked, why, and which run resulted. The band still runs on the new run, so
    the operator can see the comp is still out of band — it is simply no longer
    excluded.
    """
    with transaction() as conn:
        row = repo.open_exclusion(conn, exclusion_id)
        if row is None:
            raise LookupError(f"no open exclusion {exclusion_id}")
        line_row = repo.get_line(conn, str(row["line_id"]))
        line = repo.seller_line_for_benchmark(line_row)
        if line is None:
            raise LookupError(f"line {row['line_id']} no longer has an approved identity")
        when = row["as_of"]
        res = repo.resolve_offers(conn, wine_id=line.wine_id, vintage=line.vintage, as_of=when)
        already = [str(x["offer_pk"]) for x in repo.run_exclusions(conn, str(row["run_id"]))
                   if x["reinstated_at"] is not None or str(x["exclusion_id"]) == exclusion_id]
        run_id, check = _benchmark_with_band(conn, line, res, when, reinstated=already)
        repo.record_reinstatement(conn, exclusion_id, reinstated_by=reinstated_by,
                                  reason=reason, replacement_run_id=run_id)
    return {"exclusion_id": exclusion_id, "run_id": run_id,
            "line_id": str(row["line_id"]), "reinstated_by": reinstated_by}


# ------------------------------------------------------------------- pricing


def price_deal(deal_id: str, priced_by: str, fx_rates: Optional[dict] = None,
               deep_discount_threshold: Optional[str] = None) -> dict:
    """Price every benchmarked line of a deal from its latest run.

    `fx_rates` is {"USD": {"rate": "0.7412", "date": "2026-09-19", "source": "ECB"}}:
    the operator's rate, kept with the result so a GP can be reproduced. A line
    the rules do not determine a price for is skipped with its reason, never
    guessed at. A line that has not been benchmarked is not priced at all.
    """
    fx_rates = fx_rates or {}
    threshold = (Decimal(deep_discount_threshold) if deep_discount_threshold is not None
                 else DEEP_DISCOUNT_THRESHOLD)
    priced, skipped = {}, []
    with transaction() as conn:
        deal = repo.get_deal(conn, deal_id)
        if deal is None:
            raise LookupError(f"deal {deal_id} not found")
        for row in repo.deal_lines(conn, deal_id):
            line_id = str(row["line_id"])
            run = repo.latest_run(conn, row["line_id"])
            if run is None:
                skipped.append({"line_id": line_id, "reason": "not benchmarked"})
                continue
            fx = fx_rates.get(row["cost_currency"] or "GBP", {})
            try:
                result = price_line(
                    uk_reference=run["uk_reference"], cost=row["cost"],
                    cost_currency=row["cost_currency"],
                    fx_rate=Decimal(fx["rate"]) if fx.get("rate") else None,
                    manual_price=row["manual_price"], line_margin=row["target_margin"],
                    line_discount=row["target_discount"], deal_margin=deal["target_margin"],
                    buyer_discount=deal["buyer_discount"], margin_on_sale=deal["margin_on_sale"],
                    deep_discount_threshold=threshold)
            except CannotPrice as e:
                skipped.append({"line_id": line_id, "reason": str(e)})
                continue
            priced[line_id] = str(repo.save_pricing(
                conn, line_id=line_id, run=run, priced=result, priced_by=priced_by,
                cost=row["cost"], cost_currency=row["cost_currency"],
                fx_rate=Decimal(fx["rate"]) if fx.get("rate") else None,
                fx_rate_date=fx.get("date"), fx_source=fx.get("source")))
    return {"priced": priced, "skipped": skipped}


# ----------------------------------------------------------------- retention


DEFAULT_SNAPSHOT_RETENTION = 10


def prune_snapshots(keep: Optional[int] = None) -> dict:
    """Drop snapshots no merchant still needs (SNAPSHOT_RETENTION).

    Retention is per merchant, not global: the newest `keep` captures of each
    merchant survive whichever snapshots they happen to sit in, so pruning
    cannot take away the latest capture a benchmark would resolve. Past runs are
    self-contained and keep reading exactly as before (decision 0004).
    """
    if keep is None:
        keep = int(os.environ.get("SNAPSHOT_RETENTION", DEFAULT_SNAPSHOT_RETENTION))
    with transaction() as conn:
        deleted = repo.prune_snapshots(conn, keep)
    return {"keep": keep, "deleted": deleted}


# ------------------------------------------------- DEEP MERCHANT SEARCH


def learn_search_keys(merchant_id: str, set_by: str, *,
                      robots: Callable[[str], None] = check_robots) -> dict:
    """Read a search-only merchant's own producer index into merchant_search_key.

    The slug is the merchant's, not ours: Bordeaux Index answers to
    `producer=domaine_armand_rousseau` and 404s on the hyphen form, which is
    exactly the kind of thing that must be read rather than guessed.
    """
    spec = TARGETED.get(merchant_id)
    if spec is None:
        raise ValueError(f"{merchant_id!r} is not searched by producer")
    robots(spec.robots_url)
    printed = spec.adapter().search_keys()

    # A producer can be published under more than one slug ("chateau_haut-brion"
    # and "haut-brion" normalise alike). Those are one key with both slugs, and
    # a search unions them: dropping one would quietly halve a producer's depth.
    by_key: dict[str, list[str]] = {}
    for name, slug in printed.items():
        by_key.setdefault(norm_producer(name), []).append(slug)

    with transaction() as conn:
        for producer_key, slugs in by_key.items():
            repo.set_search_key(conn, merchant_id=merchant_id, producer_key=producer_key,
                                params={"producer_slugs": sorted(set(slugs))},
                                source="merchant_index", set_by=set_by,
                                note=f"from the merchant's own index ({len(slugs)} slug(s))")
    return {"merchant_id": merchant_id, "keys": len(by_key), "slugs": len(printed)}


def deep_search(deal_id: str, *, min_comps: int = 2, merchant_ids: Optional[Sequence[str]] = None,
                fetch: Optional[Callable] = None,
                robots: Callable[[str], None] = check_robots) -> dict:
    """Search the gaps, and only the gaps.

    A whole-book sweep cannot include a merchant that can only be queried per
    producer and vintage, so those merchants are asked afterwards, about the
    lines that came back thin: fewer than `min_comps` merchants, or never
    searched. Each search is its own capture with its own captured_at, scoped to
    that producer and vintage, exactly like any other (decision 0004).
    """
    wanted = list(merchant_ids) if merchant_ids else list(TARGETED)
    with transaction() as conn:
        targets = repo.thin_targets(conn, deal_id, min_comps)
        approved = _approved(conn)
        keys = {(m, t["wine_key"].partition("|")[0]): repo.search_key(
                    conn, m, t["wine_key"].partition("|")[0])
                for m in wanted for t in targets}

    searched, skipped = [], []
    for merchant_id in wanted:
        if merchant_id not in approved:
            skipped.append({"merchant_id": merchant_id, "reason": "not an approved merchant"})
            continue
        if merchant_id not in TARGETED:
            skipped.append({"merchant_id": merchant_id, "reason": "not a search-only merchant"})
            continue
        for target in targets:
            producer_key = target["wine_key"].partition("|")[0]
            key = keys.get((merchant_id, producer_key))
            if key is None:
                # Fail closed and say what is missing: no guessed slugs.
                skipped.append({"merchant_id": merchant_id, "producer": target["producer"],
                                "vintage": target["vintage"],
                                "reason": "no search key for this producer"})
                continue
            snapshot_id = collect_targeted(
                merchant_id, str(target["wine_id"]), target["vintage"], key["params"],
                fetch=fetch, robots=robots)
            searched.append({"merchant_id": merchant_id, "producer": target["producer"],
                             "vintage": target["vintage"], "snapshot_id": snapshot_id})
    return {"targets": len(targets), "searched": searched, "skipped": skipped}
