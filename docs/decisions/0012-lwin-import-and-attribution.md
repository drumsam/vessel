# 0012 — LWIN as the canonical spine, and where the credit line lives

**Status:** accepted in principle, 20 September 2026. Not built: waiting on the file.

## The route

With nine canonical wines the product cannot price a real cellar. The dress
rehearsal fetched 10,510 merchant records and rejected 10,301 of them as
`UNRESOLVED_IDENTITY` — 98% of everything collected, correctly, against a
nine-wine table.

Two routes were assessed.

**(a) Import the Liv-ex LWIN database. Chosen, as the spine.** It is the
canonical producer/wine list the identity layer has been missing, it carries
LWIN-7 so decision 0006's revisit condition becomes testable, and it gives
distinct codes to the pairs that must never collapse.

**(b) Bootstrap the wine table from merchant feeds. Not the primary route.** Each
distinct producer/cuvée becoming a proposed wine fails in a way that is both
silent and aimed at the exact quantity this product measures. Farr alone would
propose "Barbaresco Costa Russi, Gaja" and "Costa Russi, Gaja" as two wines;
one merchant's listing then sits under one id and another's under the other,
each line reads `ONE_COMP`, and a market with two merchants reports as no
market. The system would look cautious while quietly losing depth. It would
also have proposed thousands of wines from one day's collection, with the
duplicates indistinguishable until someone noticed two spellings of one thing.

(b) survives as a **supplement**, restricted to records that fail to resolve
against LWIN, proposed through the existing review queue, with the LWIN
cross-check available to catch the Gaja pattern.

## The licence, and what it obliges

The LWIN database is released under **CC BY 4.0**: commercial use,
modification and redistribution are all permitted. The conditions are credit, a
link to the licence, and a statement that changes were made — "in any reasonable
manner, but not in any way that suggests the licensor endorses you or your use"
— and no additional legal or technical restrictions on anyone downstream.

Liv-ex's own suggested credit is:

> WINE INDEX: LWIN BY LIV-EX / CC BY 4.0, MODIFIED

We will modify it: normalised into `wine`, matched to merchant spellings by
alias, extended with wines LWIN does not list. So "MODIFIED" is accurate and
required, not optional politeness.

## Where the credit line lives

Attribution is owed **wherever the data is used**, and the client-facing offer
is the place it is most easily forgotten. It is a product surface, not a config
value:

1. **The buyer offer document** carries the credit in its footer, beneath the
   figures, on every issued offer — including any PDF or printed rendering.
   Wording: *Wine identification: WINE INDEX: LWIN BY LIV-EX / CC BY 4.0,
   MODIFIED*, with the licence text linked.
2. **The operator console** carries it once, in the application footer, rather
   than on every screen.
3. **Any export of the wine table itself** — a CSV, an API feed, a data share —
   carries it in the payload, because that is redistribution of the data rather
   than use of it.

The footer belongs to the document template, not to an operator-editable
setting: a client document must not be able to lose its attribution because
someone cleared a field. When the import is built, that footer ships with it,
and a test asserts an issued document renders it.

## When the import is built

Not before the file is in hand. What it will need: an import job mapping LWIN's
producer/wine to `wine.producer`/`wine.cuvee` with `lwin7` populated and
`wine_key` derived as now; a rule for LWIN rows that are withdrawn or merged
upstream; and a decision on whether matching a merchant's printed name to an
LWIN canonical name is enough to let LWIN resolve identity on its own (decision
0006 says not yet, and names that as the thing to revisit).
