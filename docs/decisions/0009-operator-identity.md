# 0009 — Operator identity: the server says who, not the caller

**Status:** accepted, 20 September 2026. An external identity provider stays possible.

## Context

Until now every "who" was a free-text field the caller supplied:
`approved_by`, `priced_by`, `acknowledged_by`, `created_by`. The export gate
(0008) and the identity trail (0003, 0006) both rest on those names, and a name
a caller types is not evidence of anything. Anyone could approve an identity as
someone else.

## Decision

**Sessions.** `POST /session` with a username and password sets one cookie:
`HttpOnly`, `Secure`, `SameSite=Lax`, twelve hours. The cookie carries a random
token and nothing else, and only its SHA-256 is stored, so a leaked row cannot
be replayed as a session. Every route except `/health` and `/session` hangs off
a router-level dependency, so a new route cannot be added unauthenticated by
forgetting to add something.

**Passwords** are argon2id via argon2-cffi — a maintained library, never a
hand-rolled scheme. The hash carries its own parameters, so they can be raised
later without invalidating existing hashes; a password that verifies against an
out-of-date hash is rehashed in place. Sign-in costs a verification even when
the username is unknown, so the two cases are not distinguishable by timing.

**The server fills `approved_by`, `priced_by` and `acknowledged_by`** from the
session. The request models do not have those fields, and bodies forbid extra
keys, so a caller trying to name someone else gets a 422 rather than being
quietly ignored — being ignored would leave the caller believing it worked.

**`operator.active`** is how access is revoked. Never delete an operator: the
history points at them. Clearing `active` ends their sessions and stops sign-in,
and every audit row still resolves.

**Audit rows keep `operator_id`, not a copied name.** Renaming someone — a
married name, a correction, a "(maternity cover)" suffix — changes what is
displayed everywhere and rewrites nothing. Migration 0006 converts the existing
text columns and preserves the names already written as inactive operator rows
that cannot log in.

**No password reset flow.** An admin sets a password with
`scripts/manage_operators.py password <username>`, which also ends that operator's
sessions. A self-service reset needs email delivery, token expiry and rate
limiting, which is a system of its own; there is no reason to build it for a
handful of operators.

## Why not an external identity provider

Portability is a stated priority, and an IdP is a third-party dependency in the
sign-in path of a system that otherwise runs on standard Postgres and Redis.

It stays possible. The only coupling is who fills those three fields: one
dependency, `current_operator`, returns the operator row. An IdP would replace
the session lookup and map its subject to an `operator` row; `operator_id`
stays the thing every audit row points at, and nothing downstream changes.

## Consequence

- The frontend must sign in and send the cookie; `FRONTEND_ORIGINS` lists the
  origins allowed to do so with credentials.
- `INSECURE_COOKIES=1` exists for local HTTP development only. It has to be
  asked for: the default is `Secure`.
- Tests run the API over `https://testserver` so the real cookie flags are what
  is exercised.
