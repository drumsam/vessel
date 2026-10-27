# docs/research — what this folder is, and the rule that governs it

This folder is the **only** place a specification exists.

Research, measurement, market work and build briefs are produced in a Claude
Cowork session that runs in the cloud. That session cannot see this repository
directly; it reaches this Mac over a bridge. Everything it produces must land
**here**, as a file, before it counts as a specification.

---

## The rule

> **A spec that is not a file in `docs/research/` does not exist.**
>
> Not in a chat message. Not in a pasted summary. Not in a Claude project
> document. Not described from memory. Only here.

This is decision **0038**, and it was adopted because the alternative had
already cost real work three times:

1. `hk-vs-uk-market-reference.md` existed only in chat, so decision 0021 was
   built from figures quoted second-hand.
2. The want-list identity rules existed only in chat, so the build was
   correctly refused until they were filed.
3. `build-brief-vessel-pocket.md` was handed over as a pasted excerpt, so the
   build was correctly refused again.

In all three cases the refusal was right. The failure was upstream: the file
was never filed.

---

## Who does what

**The research session files the document.** It writes directly into this
folder over the bridge — it does not ask Doug to move a file, paste contents,
or copy anything into the repository by hand. Doug is not a file transport.

**The research session verifies before it issues a prompt.** It lists this
folder and confirms the file is present, by name and size, *before* giving
Doug anything to paste into Claude Code. If this Mac is offline, no prompt is
issued at all — the work is held until the file can be filed.

**Claude Code refuses anything it cannot read.** If a prompt names a spec that
is not in this folder, the correct response is to stop and say so, exactly as
happened above. Do not reconstruct a specification from a summary: the summary
carries the shape and loses the reasons, and the reasons are what stop the
cellar discount chain or a photo-identity auto-resolve leaking in sideways.

---

## Why files, not git commits

Filing is a **write to this folder**, not a commit. Committing from the bridge
needs file-deletion permission for git's own lock files, that permission resets
whenever the bridge reconnects, and a failed commit used to leave the document
undelivered with nothing to show for it.

So the document is written here first and always. Committing it is a separate,
ordinary step — done from this machine, by Code or by Doug, whenever
convenient. **Delivery never depends on git succeeding.**

---

## Current build brief

`build-brief-vessel-pocket.md` — VESSEL Pocket / Cellar / Ops, 27 October 2026.
Read with `architecture-vessel-pocket.md`, which is Doug's own architecture
review. Where the two differ, the build brief wins; the architecture document
carries a note at the top saying which two points were superseded.
