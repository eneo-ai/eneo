import { defineConfig, devices } from "@playwright/test";

// Drives the real web-next UI (session-cookie auth) against a running backend.
// Locally: start the backend (uvicorn :8123) + `bun run dev` (:3100), seed the
// default user, then `bun run test:e2e`. In CI (ci.yml "Frontend E2E
// (web-next)") the isolated docker stack serves the backend and the workflow
// builds the app first, so the webServer only starts the production server.
const PORT = process.env.E2E_PORT ?? "3100";

export const STORAGE_STATE = "playwright/.auth/user.json";

export default defineConfig({
  testDir: "tests",
  fullyParallel: false,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 1 : 0,
  workers: 1,
  // list: console output; html: the report CI uploads as an artifact; github:
  // inline PR annotations (CI only).
  reporter: process.env.CI ? [["list"], ["html", { open: "never" }], ["github"]] : "list",
  use: {
    baseURL: `http://localhost:${PORT}`,
    trace: "on-first-retry"
  },
  // Locally, reuse an already-running dev server (or start one). In CI, serve
  // the build from the "Build web-next for E2E" step; ENEO_BACKEND_URL and
  // SESSION_SECRET come from the job environment.
  webServer: {
    command: process.env.CI ? `bun run start --port ${PORT}` : "bun run dev",
    url: `http://localhost:${PORT}/login`,
    reuseExistingServer: !process.env.CI,
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
