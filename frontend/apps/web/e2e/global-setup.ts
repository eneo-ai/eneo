import { execSync } from "node:child_process";
import { resolve } from "node:path";

// Brings up the ephemeral test stack (docker-compose.e2e.yml) before the run and
// waits until it's healthy. Paired with global-teardown.ts, which removes it
// afterwards — so each `bun run test:e2e` seeds a fresh database and leaves
// nothing behind. Set E2E_MANAGE_STACK=0 to manage the stack yourself (e.g. when
// iterating on specs against an already-running stack).
const COMPOSE = resolve(process.cwd(), "../../../docker-compose.e2e.yml");

export default async function globalSetup() {
  if (process.env.E2E_MANAGE_STACK === "0") return;

  console.log("[e2e] starting isolated test stack…");
  execSync(`docker compose -f "${COMPOSE}" up -d --wait`, {
    stdio: "inherit",
    timeout: 240_000
  });
}
