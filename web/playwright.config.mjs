import { defineConfig } from "@playwright/test";

// The smoke test drives the real stack: API, worker, Postgres and Redis. It is
// not part of `npm test`; see e2e/README.md for how to bring the stack up.
export default defineConfig({
  testDir: "./e2e",
  timeout: 120_000,
  expect: { timeout: 20_000 },
  retries: 0,
  use: {
    baseURL: process.env.E2E_WEB_URL || "http://localhost:3077",
    screenshot: "only-on-failure",
    trace: "retain-on-failure",
  },
});
