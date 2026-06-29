import { defineConfig, devices } from "@playwright/test";

// Drives the real web-next UI (session-cookie auth) against a running backend.
// Locally: start the backend (uvicorn :8123) + `bun run dev` (:3100), seed the
// default user, then `bun run test:e2e`. In CI, point at the isolated stack.
const PORT = process.env.E2E_PORT ?? "3100";

export const STORAGE_STATE = "playwright/.auth/user.json";

export default defineConfig({
  testDir: "tests",
  fullyParallel: false,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 1 : 0,
  workers: 1,
  reporter: "list",
  use: {
    baseURL: `http://localhost:${PORT}`,
    trace: "on-first-retry"
  },
  // Reuse an already-running dev server locally; CI should start it explicitly.
  webServer: {
    command: "bun run dev",
    url: `http://localhost:${PORT}/login`,
    reuseExistingServer: true,
    timeout: 120_000
  },
  projects: [
    { name: "setup", testMatch: /auth\.setup\.ts/ },
    {
      name: "smoke",
      testMatch: /.*\.spec\.ts/,
      dependencies: ["setup"],
      use: { ...devices["Desktop Chrome"], storageState: STORAGE_STATE }
    }
  ]
});
