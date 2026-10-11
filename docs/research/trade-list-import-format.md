# What a trade list needs to contain, asked for before it exists rather than guessed at afterwards

**Status:** specification, offered ahead of the file arriving, so Doug can
ask Berry Bros. & Rudd and Jeroboams for the right thing the first time
rather than a PDF. Not built — there is no file yet. When one arrives, a
**file importer** gets built against it (`app/import/`, a new top-level
package parallel to `app/adapters/`, not a web adapter under a bigger
name): it reads a file, not a network, and normalises it through the
EXACT SAME identity resolution and `Offer` model every live adapter
already uses. Decision 0007/0016's invariants (money is `Decimal`, duty
status is explicit, commercial unit equality is exact unless derivation
is asked for) apply to an imported row exactly as they apply to a scraped
one — the pricing core has never known or cared where an `Offer` came
from, and this does not change that.

## What to ask for

CSV (or Excel saved as CSV — not a PDF, not a Word table: see below), one
row per listing, UTF-8, these columns, in any order, with these EXACT
headers:

| Column | Example | Required | Notes |
|---|---|---|---|
| `producer` | `Krug` | yes | The merchant's own wording. Never destroyed, never guessed at. |
| `cuvee` | `Grande Cuvée` | yes | Ditto. If the wine has an edition/release number distinct from vintage (Krug's own case), put it in `release_code`, not folded into `cuvee`. |
| `release_code` | `167` | no | Krug's "167ème Édition", Henri Giraud's "MV13" — only when the wine has one. Blank otherwise, never invented. |
| `vintage` | `2008` or `NV` | yes | `NV` (not blank, not `0`) for non-vintage. |
| `bottle_ml` | `750` | yes | The real bottle size in ml: `750`, `1500`, `375`, `3000`, etc. Never a format name like "magnum" — this file is read by a program, not a person. |
| `pack_size` | `1` | yes | Bottles per unit priced. `1` for a loose bottle, `6` for an original case, etc. |
| `price_gbp` | `650.00` | yes | **Per the stated `pack_size` unit**, GBP, exactly two decimal places, no currency symbol, no thousands separator. A case price is for the whole case, not per bottle — say which with `pack_size`, don't make the importer guess. |
| `duty_status` | `IB` | yes | `IB` (In Bond) or `DP` (Duty Paid). This system only ever prices In Bond (invariant 5) — a `DP` row is kept as evidence, never priced from, same as every live adapter already does. |
| `quantity` | `6` | no | Units available, in `pack_size` terms. Blank if not published — never defaulted to a number nobody stated. |
| `condition_notes` | `Original Case` | no | The dealer's own wording. A condition FLAG is never set without the prose it came from (the same rule every live adapter already follows) — send the words, the importer does the flagging. |
| `list_date` | `2026-10-20` | yes | The date the list itself is dated — not the date it was imported, not today. This is what freshness (`MAX_OFFER_AGE_DAYS`, invariant 8) is measured against, exactly as `captured_at` is for a live capture. A list with no date on it is as unusable as an undated scrape (invariant 8: undated ⇒ `STALE`). |
| `merchant_reference` | `BBR-7315079` | no | The dealer's own stock/lot code, kept verbatim for provenance, never used for identity. |

## What NOT to ask for

- **A PDF.** Price lists arrive as PDFs more often than not, and extracting a table reliably from one is its own unreliable, format-specific project — exactly the "accuracy beats coverage" trap this whole system exists to avoid, applied to parsing instead of pricing. If only a PDF is on offer, ask for the underlying spreadsheet it was printed from instead.
- **A "wine description" free-text column standing in for `producer`/`cuvee`/`vintage`/`bottle_ml` combined** (e.g. "Krug Grande Cuvée 167ème Édition 6x75cl"). Splitting that reliably is exactly the adapter-trap work this session spent on Bordeaux Index, J&B and Lay & Wheeler's own merged fields — asking the dealer's own export to keep the fields separate is strictly cheaper than reverse-engineering their formatting conventions afterwards.
- **Case price alone with no `pack_size`**, or bottle price alone with no way to tell it apart from a case price. Both numbers exist on a real dealer list; both need a label.

## How it becomes an `Offer`

One CSV row → one `app.adapters.base.Candidate` → the SAME
`registry.resolve_candidate` every live adapter calls → the SAME
`Offer` the pricing core already knows how to screen, with
`price_kind=PriceKind.ASK`, `stock_type=StockType.MERCHANT_STOCK`,
`stock_type_basis="declared"` (the dealer said so directly, same basis a
clean live SKU gets), and `captured_at` set from `list_date`, not from
when the file happened to be opened. `merchant_id` is the dealer's own id
in the `merchant` table, registered by migration exactly as a live
adapter's merchant row is — a trade list is a new SOURCE, not a new kind
of evidence, and depth counts it as one more merchant exactly as it would
a live scrape (invariant 3).

## What this is not

Not a reason to relax any screen: a trade list's In Bond ask is screened
identically to a scraped one (duty status, GBP, positive price, whole
pence, not a mixed lot). Not a second evidence type alongside ASK/BID/
INDICATION — a dealer's firm, dated ask is an ASK, full stop; there is no
reason to invent a fourth `PriceKind` for a file instead of a page. Not
built yet, and not worth building against a guessed shape — this spec
exists so the real file, when it arrives, can be matched against it
rather than reverse-engineered cold the way every live adapter's raw
shape had to be.
