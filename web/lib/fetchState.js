/**
 * Three states a screen can be in about a piece of server data, and the only
 * three a render is allowed to tell apart: `loading` (not yet known), `ok`
 * (checked — `data` may be an empty list; that is a real, checked answer),
 * and `error` (the check itself never completed). Rendering `error` the same
 * way as an empty `ok` — the shape every bare `.catch(() => setX([]))` or
 * `.catch(() => setX(null))` takes — is the bug decision 0040 names:
 * "couldn't check" must never render as "checked and clear." See
 * docs/decisions/0040.
 *
 * `fetchInto` is the one place a promise is wired to one of these three
 * states, so a call site cannot reach "ok" except by the promise actually
 * resolving, and cannot swallow a rejection by writing an empty arrow
 * function — there is no argument here that does that. A lookup that is
 * genuinely optional (nothing downstream gates on it) stays a plain
 * `.catch(() => setX(...))` at its call site, same as before — but that is
 * now a visible, deliberate choice to skip this helper, not the default.
 */
export const LOADING = { status: "loading", data: null, error: null };

export function ok(data) {
  return { status: "ok", data, error: null };
}

export function failed(error) {
  return { status: "error", data: null, error: error?.message || String(error) };
}

export function fetchInto(setState, promise) {
  setState(LOADING);
  return promise.then(
    (data) => setState(ok(data)),
    (error) => setState(failed(error)),
  );
}

/**
 * For the one shape of endpoint where "not found" is itself the real
 * answer, not a failure: a single-resource GET that 404s when the resource
 * legitimately does not exist yet (`GET /lines/{id}/benchmark` — "line has
 * not been benchmarked" — found while wiring line.jsx: a bare `fetchInto`
 * would have put a 404 straight into `error`, the exact collapse this
 * module exists to prevent, just moved one level down). Any OTHER
 * rejection — network failure, 500, anything without `status === 404` — is
 * still `failed`, same as `fetchInto`. A list endpoint never needs this:
 * every list route in this app returns `200 []` for "none", never a 404.
 */
export function fetchSingleInto(setState, promise) {
  setState(LOADING);
  return promise.then(
    (data) => setState(ok(data)),
    (error) => setState(error?.status === 404 ? ok(null) : failed(error)),
  );
}

/**
 * Decision 0038's gate, expressed as a predicate so a disabled button reads
 * from the exact same function a test calls directly — not a re-typed
 * `=== "error"` at each call site that could quietly drift. True for
 * `error` only; `loading` is deliberately not blocking (the check is mid-
 * flight, not failed) and `ok` with any data, empty or not, is a real,
 * checked answer.
 */
export function blocksAction(state) {
  return state.status === "error";
}

/**
 * What a list-shaped screen shows for its own state: `null` means "there is
 * real data, render it yourself." Otherwise a `{ text, isError }` to show
 * instead. The two cases this exists to keep apart — `error` and an empty
 * `ok` — always come back with a different `isError` and different text,
 * by construction, not by the copy someone wrote this week: this is exactly
 * the guard "two or more is always enough" didn't have (decision 0028), and
 * fetchState.test.mjs checks the property directly rather than one call
 * site's wording.
 */
export function listStateMessage(state, { empty, errorLabel = "Couldn't load" }) {
  if (state.status === "loading") return { text: "Loading…", isError: false };
  if (state.status === "error") return { text: `${errorLabel} (${state.error}).`, isError: true };
  const isEmpty = Array.isArray(state.data) ? state.data.length === 0 : !state.data;
  return isEmpty ? { text: empty, isError: false } : null;
}
