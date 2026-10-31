import { defineConfig, devices } from "@playwright/test";

// Tests use FastAPI's browser session. Set E2E_BASE_URL for a production build;
// local development starts Vite with its same-origin backend proxy.
const PORT = process.env.E2E_PORT ?? "3101";
const EXTERNAL_BASE_URL = process.env.E2E_BASE_URL;

export const STORAGE_STATE = "playwright/.auth/user.json";

export default defineConfig({
  testDir: "tests",
  fullyParallel: false,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 1 : 0,
  workers: 1,
  // list: console output; html: the report CI uploads as an artifact; github:
  // inline PR annotations (CI only).
  reporter: process.env.CI
    ? [
        ["list"],
        [
          "html",
          { open: "never", ...(EXTERNAL_BASE_URL && { outputFolder: "playwright-report-fastapi" }) }
        ],
        ["github"]
      ]
    : "list",
  outputDir: EXTERNAL_BASE_URL ? "test-results-fastapi" : undefined,
  use: {
    baseURL: EXTERNAL_BASE_URL || `http://localhost:${PORT}`,
    trace: "on-first-retry"
  },
  // Production CI supplies FastAPI's URL; local runs reuse or start Vite.
  webServer: EXTERNAL_BASE_URL
    ? undefined
    : {
        command: `bun run dev --port ${PORT}`,
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
    },
    // Performance baseline (tests/perf), only with PERF set so test:e2e is unchanged.
    ...(process.env.PERF
      ? [
          {
            name: "perf",
            testMatch: /.*\.perf\.ts/,
            dependencies: ["setup"],
            use: { ...devices["Desktop Chrome"], storageState: STORAGE_STATE }
          }
        ]
      : [])
  ]
});
