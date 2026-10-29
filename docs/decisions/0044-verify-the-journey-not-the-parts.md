# 0044 — verify the journey, not the parts

**Status:** accepted, 28 October 2026. Found live, VESSEL Pocket hosting
bring-up: `/health` read `{"database":"ok"}`, the web bundle had the
correct API URL baked in, and a protected route correctly 401'd with no
cookie — every check that was run passed. Login from Doug's phone still
failed outright. "Health is green and the bundle has the right URL" is
not "a person can use this," and nothing run up to that point would ever
have said otherwise — the same shape decision 0040 named for a single
screen, found again one layer down, in the thing meant to make screens
reachable at all.

## What was actually wrong

The web app and the API are two separate Vercel projects, hence two
origins (`uk-fine-wine-pricer-web.vercel.app`,
`uk-fine-wine-pricer-api.vercel.app`). `app/api/auth.py` sets the session
cookie `SameSite=Lax`, no `Domain` — correctly, for a single-origin app.
Across two origins, Lax cookies are never returned on the cross-site
fetch the login form makes, so the browser discards the session cookie
the instant it receives it. `FRONTEND_ORIGINS`, which drives the API's
CORS `allow_origins`, was also unset on the API project, so the POST
itself was likely blocked before the password was ever checked. Two
independent failures, same symptom, same root cause: the hosting
architecture (decision pending from the two-Vercel-projects choice,
commit `20d45b2`) was never actually exercised end to end before being
reported as "done."

**Not the fix:** `SameSite=None` or a `.vercel.app` cookie domain.
`vercel.app` is on the Public Suffix List, so a domain cookie scoped to
it is refused outright, and Safari on iOS blocks third-party cookies by
default regardless — Doug's phone is the actual target, not a
convenience.

**The fix:** one origin. `web/next.config.mjs` gained a `rewrites()`
entry proxying `/api/*` to `API_ORIGIN` (a new, server-only env var —
never `NEXT_PUBLIC_*` — naming the API project's real URL).
`NEXT_PUBLIC_API_URL`, which `web/lib/api.js` prepends to every request
path, changed from the API's absolute URL to the relative `/api`. The
browser now only ever talks to one origin; the proxy happens server-side,
invisible to it. The cookie Set by the API arrives on a response the
browser believes came from its own origin, so it is stored first-party,
and `SameSite=Lax` works exactly as designed. CORS becomes moot for this
path — the browser never makes a cross-origin request at all — so
`FRONTEND_ORIGINS` was left alone rather than papered over.

## The rule

> A check that confirms a part is reachable is not a check that the
> journey through it works. Verify the journey.

Concretely, for anything behind a login or a multi-hop request:
confirming a dependency is "ok" (a ping, a reachability probe, a bundle
containing the right constant) is necessary and was correctly done here
— but it is not sufficient, and must never be reported as if it were.
The actual test is the sequence a real user's browser performs: here,
`POST /session` followed by an authenticated `GET` using whatever the
browser would actually be left holding after the first call — not a
privileged script's own connection, which (as it did in this session, via
`.env.migrate`-sourced credentials used directly against the API, never
through the web origin) can trivially skip the exact hop that was
broken.

This generalizes past cookies: a health check that pings a queue but
never enqueues a job, a migration check that confirms a revision but
never reads a row, a deploy check that confirms a 200 but never follows
a redirect a real client would follow, are all the same shape — "the
part responds" standing in for "the thing works," which is decision
0040's fail-open pattern one level up, in infrastructure rather than a
screen.

## Consequences

- `web/next.config.mjs`: `rewrites()` proxies `/api/*` to `API_ORIGIN`.
- Vercel, `uk-fine-wine-pricer-web` project: `API_ORIGIN` added
  (server-only); `NEXT_PUBLIC_API_URL` changed from the API's absolute
  URL to `/api`. Both projects redeployed to production.
- Verified live, the actual journey rather than its parts: `GET
  /api/health` through the web origin; `POST /api/session` with real
  operator credentials, returning `Set-Cookie` with no `Domain`
  attribute; an authenticated `GET /api/deals` using only that cookie,
  returning `200`, not `401`.
- Nothing in `app/core/`, `app/pricing/`, or any locked invariant
  touched. This is hosting plumbing, not a pricing or identity change.
- No code change to `app/api/auth.py`'s cookie settings — `SameSite=Lax`,
  no `Domain`, stays correct for a single-origin app; the architecture
  was made to match the cookie, not the other way round.
