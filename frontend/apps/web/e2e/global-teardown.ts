import { execSync } from "node:child_process";
import { resolve } from "node:path";

// Removes the ephemeral test stack after the run (containers + data), so nothing
// persists between runs. Runs even when tests fail. See global-setup.ts.
const COMPOSE = resolve(process.cwd(), "../../../docker-compose.e2e.yml");

export default async function globalTeardown() {
  if (process.env.E2E_MANAGE_STACK === "0") return;

  console.log("[e2e] removing isolated test stack…");
  execSync(`docker compose -f "${COMPOSE}" down -v`, {
    stdio: "inherit",
    timeout: 120_000
  });
}
