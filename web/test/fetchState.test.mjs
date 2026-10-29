import assert from "node:assert/strict";
import test from "node:test";
import {
  blocksAction, failed, fetchInto, fetchSingleInto, listStateMessage, LOADING, ok,
} from "../lib/fetchState.js";

function capture() {
  const states = [];
  return { states, setState: (s) => states.push(s) };
}

// ---------------------------------------------------------------- fetchInto

test("fetchInto resolves to ok(data), never collapsing data into error", async () => {
  const { states, setState } = capture();
  await fetchInto(setState, Promise.resolve(["a wine"]));
  assert.equal(states[0], LOADING);
  assert.deepEqual(states[1], { status: "ok", data: ["a wine"], error: null });
});

test("fetchInto resolves to ok([]) on an empty-but-successful fetch -- empty is a real answer", async () => {
  const { states, setState } = capture();
  await fetchInto(setState, Promise.resolve([]));
  assert.equal(states[1].status, "ok");
  assert.deepEqual(states[1].data, []);
});

test("a rejected promise produces failed, never ok with empty data standing in for it", async () => {
  const { states, setState } = capture();
  await fetchInto(setState, Promise.reject(new Error("network down")));
  const final = states[states.length - 1];
  assert.equal(final.status, "error");
  assert.notEqual(final.status, "ok");
  assert.equal(final.data, null);
  assert.equal(final.error, "network down");
});

test("loading, ok, and error are three structurally distinct states, not two with a flag", () => {
  const states = [LOADING, ok([]), ok(["x"]), failed(new Error("boom"))];
  const statuses = new Set(states.map((s) => s.status));
  assert.equal(statuses.size, 3, "expected exactly loading/ok/error, no fourth or collapsed state");
  // ok([]) (checked, empty) and failed(...) (couldn't check) must never be
  // the same status -- this is the exact collapse decision 0040 is about.
  assert.notEqual(ok([]).status, failed(new Error("x")).status);
});

test("failed() always carries a message, even from a non-Error rejection", () => {
  assert.equal(failed("plain string reason").error, "plain string reason");
  assert.equal(failed(new Error("an Error")).error, "an Error");
});

// ------------------------------------------------------------ fetchSingleInto

test("fetchSingleInto treats a 404 as a real, checked ok(null) -- not a failure", async () => {
  const { states, setState } = capture();
  const notFound = Object.assign(new Error("line has not been benchmarked"), { status: 404 });
  await fetchSingleInto(setState, Promise.reject(notFound));
  const final = states[states.length - 1];
  assert.equal(final.status, "ok");
  assert.equal(final.data, null);
});

test("fetchSingleInto still treats a non-404 rejection as failed", async () => {
  const { states, setState } = capture();
  const serverError = Object.assign(new Error("internal server error"), { status: 500 });
  await fetchSingleInto(setState, Promise.reject(serverError));
  const final = states[states.length - 1];
  assert.equal(final.status, "error");
  assert.equal(final.error, "internal server error");
});

// ------------------------------------------------------------------ blocksAction

test("decision 0038's gate: a failed want-list check blocks the action", () => {
  assert.equal(blocksAction(failed(new Error("timed out"))), true);
});

test("blocksAction does not block on loading or on a checked, empty result", () => {
  assert.equal(blocksAction(LOADING), false);
  assert.equal(blocksAction(ok([])), false);
  assert.equal(blocksAction(ok([{ producer: "Comtes Lafon" }])), false);
});

// -------------------------------------------------------------- listStateMessage
//
// One test per screen this actually gates (decision 0040's instances 2-4),
// each using that screen's own real empty/errorLabel copy -- so a change
// that makes a specific call site's "couldn't load" text collide with its
// own "checked, empty" text fails here, not in production.

test("queue page: LWIN conflicts -- couldn't load is distinct from None open", () => {
  const empty = listStateMessage(ok([]), { empty: "None open.", errorLabel: "Couldn't load LWIN conflicts" });
  const error = listStateMessage(failed(new Error("timeout")),
    { empty: "None open.", errorLabel: "Couldn't load LWIN conflicts" });
  assert.equal(empty.isError, false);
  assert.equal(error.isError, true);
  assert.notEqual(empty.text, error.text);
  assert.match(error.text, /timeout/);
});

test("queue page: alias suggestions -- couldn't load is distinct from None yet", () => {
  const empty = listStateMessage(ok([]), { empty: "None yet.", errorLabel: "Couldn't load alias suggestions" });
  const error = listStateMessage(failed(new Error("timeout")),
    { empty: "None yet.", errorLabel: "Couldn't load alias suggestions" });
  assert.equal(empty.isError, false);
  assert.equal(error.isError, true);
  assert.notEqual(empty.text, error.text);
});

test("line.jsx: couldn't load the benchmark is distinct from Not benchmarked yet", () => {
  const empty = listStateMessage(ok(null),
    { empty: "Not benchmarked yet.", errorLabel: "Couldn't load the benchmark" });
  const error = listStateMessage(failed(new Error("connection refused")),
    { empty: "Not benchmarked yet.", errorLabel: "Couldn't load the benchmark" });
  assert.equal(empty.text, "Not benchmarked yet.");
  assert.equal(empty.isError, false);
  assert.equal(error.isError, true);
  assert.notEqual(empty.text, error.text);
});

test("lines/page.jsx: couldn't load buyer offers is distinct from none issued yet", () => {
  const empty = listStateMessage(ok([]),
    { empty: "No buyer offers issued yet.", errorLabel: "Couldn't load buyer offers for this deal" });
  const error = listStateMessage(failed(new Error("502")),
    { empty: "No buyer offers issued yet.", errorLabel: "Couldn't load buyer offers for this deal" });
  assert.equal(empty.isError, false);
  assert.equal(error.isError, true);
  assert.notEqual(empty.text, error.text);
});

test("listStateMessage returns null once there is real data -- the caller renders it, not a message", () => {
  assert.equal(listStateMessage(ok([{ conflict_id: "1" }]), { empty: "None open." }), null);
  assert.equal(listStateMessage(ok({ uk_floor: "100.00" }), { empty: "Not benchmarked yet." }), null);
});

test("listStateMessage surfaces Loading as its own state, never confused with ok or error", () => {
  const loading = listStateMessage(LOADING, { empty: "None yet." });
  assert.equal(loading.isError, false);
  assert.notEqual(loading.text, "None yet.");
});
