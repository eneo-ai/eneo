import { exec } from "node:child_process";
import { resolve } from "node:path";

// Brings up the ephemeral test stack (docker-compose.e2e.yml) before the run and
// waits until it's healthy. Paired with global-teardown.ts, which removes it
// afterwards — so each `bun run test:e2e` seeds a fresh database and leaves
// nothing behind. Set E2E_MANAGE_STACK=0 to manage the stack yourself (e.g. when
// iterating on specs against an already-running stack, including `--ui`).
const COMPOSE = resolve(process.cwd(), "../../../docker-compose.e2e.yml");
const SERVICES = ["e2e-db", "e2e-redis", "e2e-mock-model", "e2e-backend"];

// `docker compose up --wait` is silent while healthchecks run (backend can take
// ~30-60s), so a manual run looks hung. Poll `ps` alongside the wait and print a
// per-service health line each tick so you can see the stack come up.
function printStatus(): Promise<void> {
  return new Promise((res) => {
    exec(
      `docker compose -f "${COMPOSE}" ps --format '{{.Service}}=>{{if .Health}}{{.Health}}{{else}}{{.State}}{{end}}'`,
      (err, stdout) => {
        if (!err && stdout.trim()) {
          const health = new Map(
            stdout
              .trim()
              .split("\n")
              .map((l) => l.split("=>") as [string, string])
          );
          const line = SERVICES.map((s) => `${s}=${health.get(s) ?? "pending"}`).join("  ");
          console.log(`[e2e]   ${line}`);
        }
        res();
      }
    );
  });
}

export default async function globalSetup() {
  if (process.env.E2E_MANAGE_STACK === "0") return;

  console.log("[e2e] starting isolated test stack (db, redis, mock-model, backend)…");

  const child = exec(`docker compose -f "${COMPOSE}" up -d --wait`);
  child.stdout?.pipe(process.stdout);
  child.stderr?.pipe(process.stderr);

  const poll = setInterval(() => void printStatus(), 3000);
  try {
    await new Promise<void>((res, rej) => {
      child.on("exit", (code) =>
        code === 0 ? res() : rej(new Error(`[e2e] \`compose up\` exited with ${code}`))
      );
      child.on("error", rej);
    });
  } finally {
    clearInterval(poll);
  }

  await printStatus();
  console.log("[e2e] stack healthy ✔");
}
