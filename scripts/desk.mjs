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
import { spawn } from "node:child_process";
import { existsSync, mkdirSync, openSync, writeSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

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

async function main() {
  const alreadyRunning = await httpUp(`${API_URL}/session`) && await httpUp(`${WEB_URL}/login`);
  if (alreadyRunning) {
    await printDealUrl();
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

  console.log("Loading the demo deal…");
  const seedOut = await captureOutput(
    VENV_PYTHON, ["scripts/seed_cellar_desk_demo.py"],
    { cwd: ROOT, env: { ...env, PYTHONPATH: ROOT } });
  const dealId = /deal_id=(\S+)/.exec(seedOut)?.[1];
  const username = /operator_username=(\S+)/.exec(seedOut)?.[1];
  if (!dealId || !username) throw new Error(`could not read the seed script's output: ${seedOut}`);

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

  await printDealUrl(dealId, username);
  console.log("\nPress Ctrl-C to stop.");
  await new Promise(() => {}); // run until Ctrl-C

  async function printDealUrl(knownDealId, knownUsername) {
    let dealUrl, user = knownUsername || "deskdemo";
    if (knownDealId) {
      dealUrl = `${WEB_URL}/deals/${knownDealId}`;
    } else {
      // Reused an already-running instance: ask it who the demo deal is.
      const seedOut2 = await captureOutput(
        VENV_PYTHON, ["scripts/seed_cellar_desk_demo.py"],
        { cwd: ROOT, env: { ...process.env, DATABASE_URL, PYTHONPATH: ROOT } }).catch(() => "");
      const id = /deal_id=(\S+)/.exec(seedOut2)?.[1];
      dealUrl = id ? `${WEB_URL}/deals/${id}` : `${WEB_URL}`;
    }
    console.log("");
    console.log("  Cellar Desk is ready.");
    console.log("");
    console.log(`  Open:      ${dealUrl}`);
    console.log(`  Username:  ${user}`);
    console.log(`  Password:  desk-demo-password`);
    // decision 0032: never leave it ambiguous whether this is demo data or
    // a real cellar. desk.sh only ever drives the local, embedded database
    // -- losing it costs nothing -- so the line says so every time, not
    // just the first time.
    console.log(`  Database:  localhost:${PG_PORT}/${PG_DATABASE} (local demo data — never a real cellar)`);
    console.log("");
  }
}

main().catch((err) => {
  console.error("\nCellar Desk failed to start:", err.message);
  console.error(`Logs are in ${LOG_DIR}`);
  shutdown();
});
