import { defineConfig, devices } from "@playwright/test";

// End-to-end tests run against a production preview of the built app, wired to
// the ISOLATED test backend from docker-compose.e2e.yml (port 8124, its own
// `eneo_test` database, dummy model keys). See frontend/TESTING.md for the full
// flow and how to bring the stack up.
//
// IMPORTANT: the webServer step runs `vite build`, which writes to the shared
// .svelte-kit output. Do NOT run the E2E suite while a dev server is live — the
// concurrent build corrupts .svelte-kit. Stop dev first (or run this in CI).
const PORT = 4173;
const BACKEND_URL = process.env.E2E_BACKEND_URL ?? "http://localhost:8124";

// Reused login session, produced once by auth.setup.ts.
export const STORAGE_STATE = "playwright/.auth/user.json";

export default defineConfig({
  testDir: "tests",
  // Specs only by default; the setup project opts into auth.setup.ts explicitly,
  // so the chromium project never re-runs the setup as a test.
  testMatch: /(.+\.)?(test|spec)\.[jt]s/,
  use: {
    baseURL: `http://localhost:${PORT}`,
    trace: "on-first-retry"
  },
  projects: [
    // 1) Authenticate once and persist the session.
    { name: "setup", testMatch: /auth\.setup\.ts/ },
    // 2) Everything else reuses that session.
    {
      name: "chromium",
      use: { ...devices["Desktop Chrome"], storageState: STORAGE_STATE },
      dependencies: ["setup"]
    }
  ],
  webServer: {
    command: `bun run build && bun run preview --port ${PORT} --strictPort`,
    port: PORT,
    reuseExistingServer: !process.env.CI,
    timeout: 180_000,
    env: {
      // Point the previewed app at the isolated test backend, and match its
      // cookie-signing secret so the session cookie validates.
      ENEO_BACKEND_URL: BACKEND_URL,
      PUBLIC_ENEO_BACKEND_URL: BACKEND_URL,
      JWT_SECRET: process.env.E2E_JWT_SECRET ?? "1234"
    }
  }
});
