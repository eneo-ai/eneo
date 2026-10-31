import { defineConfig, devices } from "@playwright/test";

// The full suite verifies production CSP and built chunks served by FastAPI.
const BASE_URL = process.env.E2E_BASE_URL;
if (!BASE_URL) {
  throw new Error("Set E2E_BASE_URL to a FastAPI-served Vite build; see frontend/TESTING.md.");
}

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
    ? [["list"], ["html", { open: "never", outputFolder: "playwright-report-fastapi" }], ["github"]]
    : "list",
  outputDir: "test-results-fastapi",
  use: {
    baseURL: BASE_URL,
    trace: "on-first-retry"
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
