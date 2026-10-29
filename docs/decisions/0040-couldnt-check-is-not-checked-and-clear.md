# 0040 — "couldn't check" is not "checked and clear"

**Status:** accepted, 24 October 2026. Found live: `scripts/desk.sh`
printed `http://localhost:3000/deals/undefined` after a closed terminal
killed the embedded Postgres while the detached `uvicorn`/`next`
processes survived as orphans — the already-running banner re-ran the
seed scripts, their output failed silently against the dead database
(`.catch(() => "")`), and `undefined` was interpolated straight into the
URL. Doug: "that is the third time in this project that a silent failure
became a confident wrong answer" — after the UUID-in-an-error-message
instance (decision 0037) and the "two or more is always enough" copy
that outlived decision 0028's own correction. This decision audits for
the pattern rather than the one instance, across `app/`, `scripts/`, and
`web/`.

## The rule

> Couldn't check must never render as checked and clear.

A screen (or a script) reporting on a piece of server data is in exactly
one of three states, and no render may collapse two of them into the
same shape:

1. **checked, found something** — real data, shown.
2. **checked, found nothing** — a real, checked answer; an empty list or
   a null is a legitimate thing to render plainly.
3. **couldn't check** — the request itself never completed. This must
   look different from both of the above, and it must block whatever
   the check was gating.

The bug shape audited for: a `.catch()` (JS) or a swallowing `except`
(Python) that resets state to the same value state (2) uses, so a
network blip or a dead dependency renders identically to "nothing to
see here." This is a different failure from `lea_sandeman.py`'s
`parse_money`/`lw_trading.py`'s `parse_price`, which return `None` on an
unparseable value — `None` propagates as "unparseable" and can never
become a wrong price. Fail-safe and fail-silent are different things;
only the second is the bug this decision is about.

## What was found, ranked by what it costs when it goes wrong

1. **`web/app/evaluate/page.jsx`** — the want-list match check (decision
   0038's safety gate for ten Burgundy producers worth 5–20× on a wrong
   identity) reset to an empty match list on any failure, identical to
   "checked, not on the list." On these producers an unverified identity
   is worth more than a fast screen.
2. **`web/app/queue/page.jsx`** — the LWIN-conflict and alias-suggestion
   queues rendered "None open." / "None yet." whether the queue was
   really empty or the fetch failed. The exception queue is the one
   screen whose entire job is telling Doug what needs a decision; a
   silent failure there says "nothing does."
3. **`web/app/deals/[dealId]/lines/line.jsx`** — a failed benchmark fetch
   rendered "Not benchmarked yet.", the same message a line that
   genuinely has never been run shows. Lower stakes than the two above
   (this is the pipeline detail page, not the Cellar Desk default view),
   but the same shape.
4. **`web/app/deals/[dealId]/lines/page.jsx`** — a failed buyer-offers
   fetch rendered as an empty history, same treatment, lowest stakes
   (read-only record, not a gate).
5. **`scripts/desk.mjs`** — already fixed, same session: the banner now
   queries the database directly for both deal ids on every run rather
   than trusting a seed script's stdout, and prints "deal not found —
   run with --reseed" instead of interpolating a missing id into a URL.

Checked and found fine, for the contrast: `app/adapters/lea_sandeman.py`
and `lw_trading.py`'s parse functions (above); `web/lib/api.js`'s
`request()`, which always throws a real error — the leak only happens at
a call site that discards it; `web/app/chrome.jsx`'s session check and
`offer/page.jsx`'s own benchmark-run fetch, which already fail toward
"logged out" / a distinct `{error}` object rather than a confident wrong
answer; `app/api/main.py`'s Redis-ping fallback, deliberate and already
documented in place.

## The fix

`web/lib/fetchState.js` (new): three states — `loading`, `ok(data)`
(data may be an empty list; that is real), `failed(error)` — and
`fetchInto(setState, promise)`, the one place a promise is wired to
React state for this pattern. There is no argument to `fetchInto` that
collapses `error` into `ok`; a call site that wants the old
swallow-and-default behaviour has to not call this helper, which makes
that choice visible in the diff rather than indistinguishable from the
bug.

Wiring `line.jsx` found a second shape of the same collapse one level
down: `GET /lines/{id}/benchmark` returns a real `404` for "this line
has not been benchmarked yet" — a legitimate answer, not a failure — so
a bare `fetchInto` would have put that 404 straight into `error`,
indistinguishable from a dead API. `fetchSingleInto` is the one
exception: it treats `error.status === 404` as `ok(null)` and anything
else as `failed`, for the one shape of endpoint (a single-resource GET)
where "not found" is itself the real answer. Every list endpoint this
app has returns `200 []` for "none," never a 404, so `fetchInto` is
right for all three of the other screens.

`blocksAction(state)` is `state.status === "error"`, named and exported
so the Evaluate button's `disabled` expression and a test call the exact
same function rather than each re-typing `=== "error"` and risking one
of them drifting. `listStateMessage(state, {empty, errorLabel})` is the
one function all four "is this empty or did it fail" render branches
call: it returns `null` once there is real data (render it yourself), or
`{text, isError}` otherwise — `error` and an empty `ok` always come back
with a different `isError`, not just different copy, so the two can
never silently converge again.

All four screens above now hold the three-state object instead of a
bare array/object/null, render a distinct, Retry-backed branch through
`listStateMessage` (`queue/page.jsx` factors this into a local
`QueueMessage` component used twice), and — `evaluate/page.jsx` only,
because this is the one gate the UI itself is responsible for — disable
the "Evaluate" submit button via `blocksAction(wantListCheck)` while the
want-list check is in the error state. The other three are display
screens; nothing downstream in this app lets them skip the real gate
(decision 0038's identity acknowledgement, decision 0037's acceptance
gate), so the fix there is making the failure visible and retryable,
not adding a new block.

Not touched: `/wines` enrichment lookups (dropdown options and
display-name lookups) across these same files, `auctionHealth`/
`auctionLots` in `line.jsx`, and `workerUp` in `lines/page.jsx` — these
already fail toward an honestly-empty or honestly-disabled state (an
empty dropdown blocks its own form by construction; `workerUp: false`
disables a button rather than enabling one incorrectly), not a
plausible wrong answer. Widening the audit to every catch in the
frontend was considered and rejected as scope Doug did not ask for;
`fetchInto` exists so the next one found is a small diff, not a second
audit.

## What this is not

Not a data-fetching library. No caching, no retries, no request
deduplication — `fetchInto` is exactly as big as the three states it
exists to keep apart, nothing else.

Not a change to any gate's actual logic. `requires_acknowledgement`,
`want_list_ack_by`, and every flag behind them are untouched; this is
only about whether a screen can lie about having checked them.

## Consequences

- `web/lib/fetchState.js` (new): `LOADING`, `ok`, `failed`, `fetchInto`,
  `fetchSingleInto`, `blocksAction`, `listStateMessage`.
- `web/test/fetchState.test.mjs` (new, 15 tests): `fetchInto` cannot
  collapse a rejection into `ok` (asserted directly, including that
  `ok([])` and `failed(...)` are never the same status); `fetchSingleInto`
  treats a 404 as `ok(null)` and anything else as `failed`; `blocksAction`
  is true only for `failed` — decision 0038's gate, checked as a pure
  predicate rather than only read off a disabled button; one test per
  remaining screen (LWIN conflicts, alias suggestions, the benchmark,
  buyer offers) asserting `listStateMessage`'s "couldn't load" and
  "checked, empty" outputs differ in both text and `isError` for that
  screen's own real copy, so the specific collapse "two or more is
  always enough" suffered cannot recur silently at any of these four
  call sites. This is a test, not a click-through, on purpose: it
  survives the next edit in a way a manual check does not.
- `web/app/evaluate/page.jsx`: `matches` → `wantListCheck` (three-state);
  submit button disabled via `blocksAction(wantListCheck)`; a Retry
  action.
- `web/app/queue/page.jsx`: `conflicts`, `suggestions` → three-state,
  both rendered through a local `QueueMessage` component wrapping
  `listStateMessage`; `None open.`/`None yet.` now mean only "checked,
  empty."
- `web/app/deals/[dealId]/lines/line.jsx`: `run` → `runState`, loaded via
  `fetchSingleInto` (the 404-is-not-a-failure case); `run` kept as a
  derived local for the existing `run?.field` call sites, which are
  otherwise unchanged; the Market Evidence header renders through
  `listStateMessage`.
- `web/app/deals/[dealId]/lines/page.jsx`: `offers` → three-state,
  rendered through `listStateMessage`; gained an explicit "No buyer
  offers issued yet." empty state where previously nothing rendered at
  all for both "empty" and "failed" alike.
- `scripts/desk.mjs`: see the self-healing and banner fixes landed
  earlier this session (the `undefined`-URL bug and the partial-stack
  health check) — recorded here as the evidence for the pattern, not
  re-described.
- `web` test suite: 44/44 passing (29 pre-existing + 15 new, all in
  `fetchState.test.mjs`). All four edited routes confirmed compiling
  and serving 200 on the live dev server with no errors in
  `.localdb/logs/web.log`. No browser automation tool was available in
  this session to click through the failure path live in a real
  browser; the tests above are the verification that survives the next
  edit, which a click-through would not have.
- `CLAUDE.md` gains this as a named rule alongside the existing
  invariants.
