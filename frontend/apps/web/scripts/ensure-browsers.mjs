// Ensures the Chromium build that Vitest browser mode (component tests) and
// Playwright (E2E) both need is present. A fresh checkout has node_modules but no
// browser binary, so the first component-test/E2E run otherwise dies with a
// cryptic "Executable doesn't exist". Stat the expected path (fast, offline-safe)
// and only download on a real miss — so this is a no-op on every run after the
// first, including watch-mode restarts.
import { existsSync } from "node:fs";
import { execSync } from "node:child_process";

let needed;
try {
  const { chromium } = await import("playwright");
  needed = !existsSync(chromium.executablePath());
} catch {
  // playwright not resolvable yet → let the installer sort it out.
  needed = true;
}

if (needed) {
  console.log("[test] Chromium not found — installing it once (first run only)…");
  execSync("bun x playwright install chromium chromium-headless-shell", { stdio: "inherit" });
}
