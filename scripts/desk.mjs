#!/usr/bin/env node
// The one command Doug types to look at Cellar Desk. Invoked by desk.sh,
// never directly: desk.sh ensures .venv and node_modules exist first, since
// this file assumes both are already there.
//
// No Docker, no psql, no Postgres.app on Doug's machine -- embedded-postgres
// (the same package used for this repo's own Postgres test runs) gives a
// real Postgres with no system install and no daemon to manage by hand.
//
// The data directory lives under the repo, at .localdb/ (gitignored), not
// under /private/tmp: an embedded Postgres data directory placed there once,
// during this feature's own development, was silently wiped mid-session and
// took the whole Champagne sweep's data with it. Under the repo it survives
// a reboot and is one `rm -rf .localdb` away from a clean slate.
//
// No Redis, no worker: Cellar Desk only reads prices that already exist
// (pricing_result, via the API), so nothing here needs the job queue. The
// API boots fine without REDIS_URL set -- only the queue-backed endpoints
// (collect/benchmark/price, /health) would fail, and Cellar Desk calls none
// of them.
import EmbeddedPostgres from "embedded-postgres";
import pgModule from "pg";
import { spawn } from "node:child_process";
import { existsSync, mkdirSync, openSync, writeSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const { Client: PgClient } = pgModule;

const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..");
const DATA_DIR = join(ROOT, ".localdb", "pgdata");
const LOG_DIR = join(ROOT, ".localdb", "logs");
const PG_PORT = 5432;
const PG_USER = "postgres";
const PG_PASSWORD = "deskdemo"; // local-only, never network-exposed; not a secret worth protecting
const PG_DATABASE = "pricer_desk";
const DATABASE_URL = `postgresql://${PG_USER}:${PG_PASSWORD}@localhost:${PG_PORT}/${PG_DATABASE}`;
const API_PORT = 8000;
const WEB_PORT = 3000;
const API_URL = `http://localhost:${API_PORT}`;
const WEB_URL = `http://localhost:${WEB_PORT}`;
const VENV_PYTHON = join(ROOT, ".venv", "bin", "python");
const VENV_ALEMBIC = join(ROOT, ".venv", "bin", "alembic");

// Must match DEAL_NAME in seed_cellar_desk_demo.py and seed_cellar_desk_real.py
// exactly -- these are the lookup keys, not labels.
const DEMO_DEAL_NAME = "WFS Cellar · Champagne (desk demo)";
const REAL_DEAL_NAME = "WFS Cellar · Champagne";
const DEMO_USERNAME = "deskdemo"; // OPERATOR_USERNAME in seed_cellar_desk_demo.py

mkdirSync(LOG_DIR, { recursive: true });
const logFd = (name) => openSync(join(LOG_DIR, name), "a");

const children = [];

function spawnTracked(command, args, options) {
  const child = spawn(command, args, { ...options, detached: true });
  children.push(child);
  return child;
}

async function httpUp(url) {
  try {
    await fetch(url, { signal: AbortSignal.timeout(2000) });
    return true; // any response at all -- even a 401 or 500 -- means the server is listening
  } catch {
    return false;
  }
}

// A health check, not just a liveness check: uvicorn answering at all (even
// a 500) is exactly what an orphaned API with a dead Postgres behind it
// looks like from the outside, which is the actual failure this is for --
// /health's own `database` field is what distinguishes "up" from "up but
// lying about it."
async function apiHealthy() {
  try {
    const res = await fetch(`${API_URL}/health`, { signal: AbortSignal.timeout(2000) });
    if (!res.ok) return false;
    const body = await res.json();
    return body.database === "ok";
  } catch {
    return false;
  }
}

async function pgHealthy() {
  try {
    await withPgClient((client) => client.query("SELECT 1"));
    return true;
  } catch {
    return false;
  }
}

async function checkStack() {
  const [postgres, api, web] = await Promise.all([pgHealthy(), apiHealthy(), httpUp(`${WEB_URL}/login`)]);
  return { postgres, api, web };
}

async function pidsOnPort(port) {
  try {
    const out = await captureOutput("lsof", ["-ti", `tcp:${port}`, "-sTCP:LISTEN"], {});
    return out.split("\n").map((s) => s.trim()).filter(Boolean).map(Number);
  } catch {
    return []; // lsof exits non-zero when nothing is listening -- not a failure here
  }
}

async function killPort(port, label) {
  const pids = await pidsOnPort(port);
  if (pids.length === 0) return;
  console.log(`  stopping ${label} (pid ${pids.join(", ")})…`);
  for (const pid of pids) {
    try { process.kill(pid, "SIGTERM"); } catch { /* already gone */ }
  }
  try {
    await waitUntil(`${label} to stop`, async () => (await pidsOnPort(port)).length === 0,
      { timeoutMs: 10_000, intervalMs: 300 });
  } catch {
    for (const pid of await pidsOnPort(port)) {
      try { process.kill(pid, "SIGKILL"); } catch { /* already gone */ }
    }
  }
}

// Never attach to a partially-alive stack (decision: a closed terminal can
// SIGHUP Postgres while the detached uvicorn/next survive as orphans --
// confirmed live, 24 October 2026 -- and an orphaned API still answers
// requests, just with no database behind it, which looks like a bug in the
// app rather than an absent one). The fix is not a supervisor: on every run,
// check all three, and if anything is inconsistent, stop whatever is left
// on all three ports and start the whole stack fresh. Doug's only recovery
// action, ever, is to run desk.sh again.
async function healStack(status) {
  console.log(
    `Found a partially-alive stack (database ${status.postgres ? "up" : "DOWN"}, ` +
    `API ${status.api ? "up" : "DOWN"}, web app ${status.web ? "up" : "DOWN"}). ` +
    `Never attaching to a partial stack -- stopping everything and starting fresh.`);
  await killPort(WEB_PORT, "the orphaned web app");
  await killPort(API_PORT, "the orphaned API");
  await killPort(PG_PORT, "the orphaned database");
}

async function waitUntil(label, check, { timeoutMs = 60_000, intervalMs = 500 } = {}) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    if (await check()) return;
    await new Promise((r) => setTimeout(r, intervalMs));
  }
  throw new Error(`${label} did not become ready within ${timeoutMs}ms`);
}

function run(command, args, options) {
  return new Promise((resolve, reject) => {
    const child = spawn(command, args, options);
    let stderr = "";
    child.stderr?.on("data", (d) => { stderr += d.toString(); });
    child.on("close", (code) => {
      code === 0 ? resolve() : reject(new Error(`${command} ${args.join(" ")} exited ${code}: ${stderr.slice(-2000)}`));
    });
  });
}

function captureOutput(command, args, options) {
  return new Promise((resolve, reject) => {
    const child = spawn(command, args, options);
    let stdout = "", stderr = "";
    child.stdout?.on("data", (d) => { stdout += d.toString(); });
    child.stderr?.on("data", (d) => { stderr += d.toString(); });
    child.on("close", (code) => {
      code === 0 ? resolve(stdout) : reject(new Error(`${command} ${args.join(" ")} exited ${code}: ${stderr.slice(-2000)}`));
    });
  });
}

let shuttingDown = false;
async function shutdown() {
  if (shuttingDown) return;
  shuttingDown = true;
  console.log("\nShutting down…");
  for (const child of children) {
    try { process.kill(-child.pid, "SIGTERM"); } catch { /* already gone */ }
  }
  await new Promise((r) => setTimeout(r, 500));
  if (pg) await pg.stop().catch(() => {});
  process.exit(0);
}
process.on("SIGINT", shutdown);
process.on("SIGTERM", shutdown);

let pg;

// The banner must describe reality, never what a seed script merely claimed
// to have done -- a connection refused or a lookup miss has to surface as an
// error, not an "undefined" baked into a URL.
async function withPgClient(fn) {
  const client = new PgClient({ connectionString: DATABASE_URL });
  await client.connect();
  try {
    return await fn(client);
  } finally {
    await client.end();
  }
}

async function lookupDealIds() {
  return withPgClient(async (client) => {
    const { rows } = await client.query(
      "SELECT name, deal_id FROM deal WHERE name = ANY($1)", [[DEMO_DEAL_NAME, REAL_DEAL_NAME]]);
    const byName = new Map(rows.map((r) => [r.name, r.deal_id]));
    return { dealId: byName.get(DEMO_DEAL_NAME) ?? null, realDealId: byName.get(REAL_DEAL_NAME) ?? null };
  });
}

// --reseed only: old demo deals are dropped first so re-running it does not
// accumulate a second (or third, or tenth) copy under the same name.
async function dropDemoDeals() {
  await withPgClient((client) =>
    client.query("DELETE FROM deal WHERE name = ANY($1)", [[DEMO_DEAL_NAME, REAL_DEAL_NAME]]));
}

async function runSeedScripts() {
  const env = { ...process.env, DATABASE_URL, PYTHONPATH: ROOT };
  console.log("Loading the demo deal…");
  await captureOutput(VENV_PYTHON, ["scripts/seed_cellar_desk_demo.py"], { cwd: ROOT, env });
  console.log("Loading the real Champagne sweep…");
  await captureOutput(VENV_PYTHON, ["scripts/seed_cellar_desk_real.py"], { cwd: ROOT, env });
}

function dealUrl(dealId) {
  return dealId ? `${WEB_URL}/deals/${dealId}` : "deal not found — run with --reseed";
}

async function printDealUrls() {
  const { dealId, realDealId } = await lookupDealIds();
  console.log("");
  console.log("  Cellar Desk is ready.");
  console.log("");
  console.log(`  Your real Champagne sweep:  ${dealUrl(realDealId)}`);
  console.log(`  Fast three-line fixture:    ${dealUrl(dealId)}`);
  console.log("");
  console.log(`  Username:  ${DEMO_USERNAME}`);
  console.log(`  Password:  desk-demo-password`);
  // decision 0032: never leave it ambiguous whether this is demo data or
  // a real cellar. desk.sh only ever drives the local, embedded database
  // -- losing it costs nothing -- so the line says so every time, not
  // just the first time.
  console.log(`  Database:  localhost:${PG_PORT}/${PG_DATABASE} (local demo data — never a real cellar)`);
  console.log("");
}

async function main() {
  const reseed = process.argv.includes("--reseed");
  let status = await checkStack();
  const aliveCount = Number(status.postgres) + Number(status.api) + Number(status.web);
  if (aliveCount > 0 && aliveCount < 3) {
    await healStack(status);
    status = { postgres: false, api: false, web: false };
  }
  const alreadyRunning = status.postgres && status.api && status.web;

  if (alreadyRunning) {
    // The other instance owns Postgres and the servers; never touch either
    // here. A --reseed still has to run against that same live database --
    // that's the whole point of asking for one while the stack is already up.
    if (reseed) {
      console.log("Dropping existing demo deals…");
      await dropDemoDeals();
      await runSeedScripts();
    }
    await printDealUrls();
    console.log("\n(Already running from another terminal -- this one is just showing you the URL again.)");
    console.log("Press Ctrl-C to stop watching; the other instance keeps running.");
    await new Promise(() => {}); // nothing more to do here; the other instance owns the processes
    return;
  }

  const pgLog = logFd("postgres.log");
  const writeLog = (message) => { try { writeSync(pgLog, String(message)); } catch { /* ignore */ } };
  pg = new EmbeddedPostgres({
    databaseDir: DATA_DIR, port: PG_PORT, user: PG_USER, password: PG_PASSWORD,
    persistent: true, onLog: writeLog, onError: writeLog,
  });

  if (!existsSync(join(DATA_DIR, "PG_VERSION"))) {
    console.log("Setting up the local database…");
    await pg.initialise();
  }
  console.log("Starting the local database…");
  await pg.start();

  const client = pg.getPgClient();
  await client.connect();
  const { rowCount } = await client.query(
    "SELECT 1 FROM pg_database WHERE datname = $1", [PG_DATABASE]);
  if (rowCount === 0) await client.query(`CREATE DATABASE ${PG_DATABASE}`);
  await client.end();

  console.log("Applying migrations…");
  const env = { ...process.env, DATABASE_URL };
  await run(VENV_ALEMBIC, ["upgrade", "head"], { cwd: ROOT, env });

  if (reseed) {
    console.log("Dropping existing demo deals…");
    await dropDemoDeals();
  }
  await runSeedScripts();

  console.log("Starting the API…");
  const apiLog = logFd("api.log");
  spawnTracked(VENV_PYTHON, ["-m", "uvicorn", "app.api.main:app", "--port", String(API_PORT)], {
    cwd: ROOT,
    env: { ...env, FRONTEND_ORIGINS: WEB_URL, INSECURE_COOKIES: "1" },
    stdio: ["ignore", apiLog, apiLog],
  });
  await waitUntil("the API", () => httpUp(`${API_URL}/session`));

  console.log("Starting the web app…");
  const webLog = logFd("web.log");
  spawnTracked("npm", ["run", "dev", "--", "-p", String(WEB_PORT)], {
    cwd: join(ROOT, "web"),
    env: { ...process.env, NEXT_PUBLIC_API_URL: API_URL },
    stdio: ["ignore", webLog, webLog],
  });
  await waitUntil("the web app", () => httpUp(`${WEB_URL}/login`), { timeoutMs: 180_000 });

  await printDealUrls();
  console.log("\nPress Ctrl-C to stop.");
  await new Promise(() => {}); // run until Ctrl-C
}

main().catch((err) => {
  console.error("\nCellar Desk failed to start:", err.message);
  console.error(`Logs are in ${LOG_DIR}`);
  shutdown();
});
