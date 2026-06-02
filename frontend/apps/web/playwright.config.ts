import type { PlaywrightTestConfig } from "@playwright/test";

// End-to-end tests run against a production preview of the built app, served on a
// dedicated port (4173) so it never collides with `bun run dev` on 3000.
//
// IMPORTANT: the webServer step runs `vite build`, which writes to the shared
// .svelte-kit output. Do NOT run the E2E suite while a dev server is live — the
// concurrent build corrupts .svelte-kit. Either stop dev first, or start the
// preview yourself and let `reuseExistingServer` pick it up.
//
// These tests exercise real user flows and therefore need the full stack
// (backend + database) reachable from the previewed app. They are intentionally
// kept out of the default CI gate; see TESTING.md for how to run them.
const PORT = 4173;

const config: PlaywrightTestConfig = {
  testDir: "tests",
  testMatch: /(.+\.)?(test|spec)\.[jt]s/,
  use: {
    baseURL: `http://localhost:${PORT}`,
    trace: "on-first-retry"
  },
  webServer: {
    command: `bun run build && bun run preview --port ${PORT} --strictPort`,
    port: PORT,
    reuseExistingServer: !process.env.CI,
    timeout: 120_000
  }
};

export default config;
