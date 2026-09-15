import { appendFileSync } from "node:fs";
import { spawnSync } from "node:child_process";

const args = process.argv.slice(2);
const eventsPath = process.env.ENEO_FRONTEND_DEV_FIXTURE_EVENTS;

function record(event) {
  if (!eventsPath) throw new Error("Missing fixture event path.");
  appendFileSync(eventsPath, `${event}:${process.pid}\n`);
}

function runWorker(kind) {
  record(`${kind}:start`);
  let stopped = false;
  const stop = () => {
    if (stopped) return;
    stopped = true;
    record(`${kind}:stop`);
    process.exit(0);
  };
  process.on("SIGINT", stop);
  process.on("SIGTERM", stop);
  setInterval(() => {}, 60_000);
}

const command = args.join(" ");
if (command === "run --cwd packages/ui build:dev") {
  record("build:start");
} else if (command === "run --cwd packages/ui dev") {
  runWorker("ui");
} else if (command === "run --cwd apps/web dev") {
  runWorker("web");
} else {
  const delegated = spawnSync(process.execPath, args, {
    cwd: process.cwd(),
    env: process.env,
    stdio: "inherit",
  });
  if (delegated.error) throw delegated.error;
  process.exit(delegated.status ?? 1);
}
