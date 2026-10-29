# 0045 — `DEFAULT_MODEL` is already pinned; there is nothing to date

**Status:** accepted, 29 October 2026. Raised while fixing the Anthropic
provider's structured-outputs migration (decision pending that fix's own
record, same session): `app/ai/anthropic_provider.py::DEFAULT_MODEL =
"claude-sonnet-5-5"` looked like a floating alias next to a codebase that
treats "no silent behaviour drift" as load-bearing everywhere else
(`app/core/`'s locked invariants, "say so and cite evidence" for every
intentional change) — the one place that discipline didn't obviously
reach. Doug corrected the premise rather than the code: from the 4.6
generation onward, Anthropic dropped dated snapshots entirely. The
dateless ID **is** the snapshot; the documented guarantee is that the
underlying model behind `"claude-sonnet-5-5"` stays constant for the
life of that ID. A dated form (`claude-sonnet-4-5-20250929`) exists only
for pre-4.6 models, which `app/ai/` has none of.

## The rule

> `DEFAULT_MODEL` names a real, already-pinned snapshot. Do not invent a
> dated form that does not exist, here or in any future provider this
> file gains.

For a 4.6-or-later Anthropic model id, the dateless string is as fixed
as a dated one ever was for an earlier generation — pinning "harder"
would mean fabricating a date Anthropic never issued, which is worse
than doing nothing: it would look like a deliberate, verified choice
and be a guess.

## What changes, and what doesn't

Nothing in `app/ai/anthropic_provider.py` changes because of this
decision. `DEFAULT_MODEL` stays `"claude-sonnet-5-5"`, unpinned in the
sense of "no date suffix," pinned in the sense that actually matters —
behaviour does not drift under it.

## The residual risk, named rather than left implicit

Not drift — **retirement**. Each model id carries its own deprecation
schedule; Anthropic's own SDK already warns on this
(`DEPRECATED_MODELS`, read directly in
`.venv/.../anthropic/resources/messages/messages.py` while fixing the
structured-outputs call). A retired id returns a clear API error, not a
quietly different answer. Decision 0040's three-state discipline — a
provider exception is `failed`, never a silent `ok` — already turns
that error into the same visible, blocking "couldn't read this" every
other provider failure produces (`parse_state` stays `'pending'`,
retryable, never a candidate). The right outcome for a retirement is
exactly the behaviour this file already had before this decision was
ever raised; nothing new needed to be built for it.

## Consequences

- No code change. This record exists so a future reader — or a future
  Claude Code session — does not "fix" `DEFAULT_MODEL` by inventing a
  dated string that was never issued, exactly the failure mode this
  decision was raised to prevent in the first place.
- If Anthropic ever reintroduces dated snapshots for a future
  generation, or `app/ai/` gains a provider from an era that still uses
  them, this decision's reasoning — not its conclusion — is what
  transfers: pin what is actually dated, and verify the exact string
  rather than guess it, the same discipline `scripts/load_want_list_wines.py`
  already applies to a CSV row's own source citation.
