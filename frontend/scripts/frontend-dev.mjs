import { execFile, spawn } from "node:child_process";
import {
  mkdir,
  readFile,
  readlink,
  rmdir,
  unlink,
  writeFile,
} from "node:fs/promises";
import { createConnection } from "node:net";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { promisify } from "node:util";

const execFileAsync = promisify(execFile);
const scriptPath = fileURLToPath(import.meta.url);
const frontendRoot = resolve(dirname(scriptPath), "..");
const runtimeRoot = join(frontendRoot, "node_modules", ".cache", "eneo");
const lockDirectory = join(runtimeRoot, "frontend-dev.lock");
const lockOwnerPath = join(lockDirectory, "owner");
const frontendUrl = "http://localhost:3000";
const frontendPort = 3000;
const shutdownTimeoutMs = 5_000;

export function parseProcessTable(output) {
  return output
    .split("\n")
    .map((line) => line.match(/^\s*(\d+)\s+(\d+)\s+(.*)$/))
    .filter((match) => match !== null)
    .map((match) => ({
      pid: Number(match[1]),
      parentPid: Number(match[2]),
      command: match[3],
    }));
}

export function isSameCheckoutViteProcess(processRecord, workspaceRoot) {
  const viteEntrypoint = join(
    workspaceRoot,
    "apps",
    "web",
    "node_modules",
    ".bin",
    "vite",
  );
  return (
    processRecord.command.includes(viteEntrypoint) &&
    /(?:^|\s)dev(?:\s|$)/.test(processRecord.command)
  );
}

export function isControllerProcess(processRecord, workspaceRoot) {
  const absoluteScriptPath = join(workspaceRoot, "scripts", "frontend-dev.mjs");
  const runsController =
    processRecord.command.includes(absoluteScriptPath) ||
    processRecord.command.includes("scripts/frontend-dev.mjs");
  return runsController && processRecord.cwd === workspaceRoot;
}

export function classifyFrontendStatus({
  portOpen,
  processes,
  controllerPid,
  workspaceRoot,
}) {
  const vitePids = processes
    .filter((processRecord) =>
      isSameCheckoutViteProcess(processRecord, workspaceRoot),
    )
    .map((processRecord) => processRecord.pid);

  if (vitePids.length > 0) {
    return { kind: "running", vitePids, controllerPid };
  }
  if (portOpen) return { kind: "conflict" };
  if (controllerPid) return { kind: "starting", controllerPid };
  return { kind: "stopped" };
}

async function readLockOwner() {
  try {
    const pid = Number((await readFile(lockOwnerPath, "utf8")).trim());
    return Number.isInteger(pid) && pid > 0 ? pid : null;
  } catch (error) {
    if (error?.code === "ENOENT") return null;
    throw error;
  }
}

async function readProcessCwd(pid) {
  try {
    return await readlink(`/proc/${pid}/cwd`);
  } catch {
    // `/proc` is Linux-specific; macOS exposes the cwd through lsof.
  }

  try {
    const { stdout } = await execFileAsync("lsof", [
      "-a",
      "-p",
      String(pid),
      "-d",
      "cwd",
      "-Fn",
    ]);
    return stdout
      .split("\n")
      .find((line) => line.startsWith("n"))
      ?.slice(1);
  } catch {
    return undefined;
  }
}

async function readProcesses(controllerPid) {
  const { stdout } = await execFileAsync(
    "ps",
    ["-axo", "pid=,ppid=,command="],
    {
      maxBuffer: 4 * 1024 * 1024,
    },
  );
  const processes = parseProcessTable(stdout);
  const controller = processes.find(
    (processRecord) => processRecord.pid === controllerPid,
  );
  if (controller) controller.cwd = await readProcessCwd(controller.pid);
  return processes;
}

async function isPortOpen() {
  return await new Promise((resolveConnection) => {
    const socket = createConnection({ host: "127.0.0.1", port: frontendPort });
    let settled = false;
    const finish = (result) => {
      if (settled) return;
      settled = true;
      socket.destroy();
      resolveConnection(result);
    };
    socket.setTimeout(500);
    socket.once("connect", () => finish(true));
    socket.once("timeout", () => finish(false));
    socket.once("error", () => finish(false));
  });
}

async function clearLock(expectedPid) {
  const owner = await readLockOwner();
  if (expectedPid && owner !== expectedPid) return;
  try {
    await unlink(lockOwnerPath);
  } catch (error) {
    if (error?.code !== "ENOENT") throw error;
  }
  try {
    await rmdir(lockDirectory);
  } catch (error) {
    if (error?.code !== "ENOENT" && error?.code !== "ENOTEMPTY") throw error;
  }
}

async function snapshotFrontendStatus() {
  const lockOwner = await readLockOwner();
  const [processes, portOpen] = await Promise.all([
    readProcesses(lockOwner),
    isPortOpen(),
  ]);
  const controller = processes.find(
    (processRecord) =>
      processRecord.pid === lockOwner &&
      isControllerProcess(processRecord, frontendRoot),
  );
  if (lockOwner && !controller) await clearLock(lockOwner);

  return classifyFrontendStatus({
    portOpen,
    processes,
    controllerPid: controller?.pid,
    workspaceRoot: frontendRoot,
  });
}

function printStatus(status) {
  switch (status.kind) {
    case "running":
      console.log(
        `[eneo] Frontend is running at ${frontendUrl}` +
          (status.controllerPid
            ? ` (controller PID ${status.controllerPid}).`
            : "."),
      );
      if (!status.controllerPid) {
        console.log(
          '[eneo] Run "bun run dev:restart" to restart it with the UI watcher under management.',
        );
      }
      return;
    case "starting":
      console.log(
        `[eneo] Frontend is starting (controller PID ${status.controllerPid}).`,
      );
      return;
    case "conflict":
      console.log(
        `[eneo] Port ${frontendPort} is occupied by a process that does not belong to this Eneo checkout.`,
      );
      console.log("[eneo] It will not be stopped automatically.");
      return;
    case "stopped":
      console.log("[eneo] Frontend is stopped.");
  }
}

async function acquireLock() {
  await mkdir(runtimeRoot, { recursive: true });
  for (let attempt = 0; attempt < 2; attempt += 1) {
    try {
      await mkdir(lockDirectory);
      await writeFile(lockOwnerPath, `${process.pid}\n`, {
        flag: "wx",
        mode: 0o600,
      });
      return true;
    } catch (error) {
      if (error?.code !== "EEXIST") throw error;
      const status = await snapshotFrontendStatus();
      if (status.kind === "starting" || status.controllerPid) return false;
      await clearLock();
    }
  }
  return false;
}

function spawnBun(args) {
  return spawn("bun", args, {
    cwd: frontendRoot,
    env: {
      ...process.env,
      NODE_ENV: "development",
      FORCE_COLOR: process.env.FORCE_COLOR ?? "1",
    },
    stdio: "inherit",
    detached: process.platform !== "win32",
  });
}

function waitForChild(child) {
  if (child.exitCode !== null || child.signalCode !== null) {
    return Promise.resolve({ code: child.exitCode, signal: child.signalCode });
  }
  return new Promise((resolveExit) => {
    child.once("error", (error) =>
      resolveExit({ code: 1, signal: null, error }),
    );
    child.once("exit", (code, signal) => resolveExit({ code, signal }));
  });
}

function signalProcess(pid, signal, asGroup = false) {
  try {
    process.kill(asGroup && process.platform !== "win32" ? -pid : pid, signal);
  } catch (error) {
    if (error?.code !== "ESRCH") throw error;
  }
}

function signalChild(child, signal) {
  if (child.pid && child.exitCode === null && child.signalCode === null) {
    signalProcess(child.pid, signal, true);
  }
}

function delay(milliseconds) {
  return new Promise((resolveDelay) => setTimeout(resolveDelay, milliseconds));
}

async function terminateChildren(children) {
  const active = [...children].filter(
    (child) => child.exitCode === null && child.signalCode === null,
  );
  for (const child of active) signalChild(child, "SIGTERM");
  await Promise.race([
    Promise.allSettled(active.map((child) => waitForChild(child))),
    delay(shutdownTimeoutMs),
  ]);
  for (const child of active) signalChild(child, "SIGKILL");
}

async function runDevelopmentStack() {
  const initialStatus = await snapshotFrontendStatus();
  if (initialStatus.kind !== "stopped") {
    printStatus(initialStatus);
    return initialStatus.kind === "conflict" ? 1 : 0;
  }
  if (!(await acquireLock())) {
    printStatus(await snapshotFrontendStatus());
    return 0;
  }

  const children = new Set();
  let requestedSignal = null;
  const handleSignal = (signal) => {
    requestedSignal ??= signal;
    for (const child of children) signalChild(child, "SIGTERM");
  };
  const handleInterrupt = () => handleSignal("SIGINT");
  const handleTermination = () => handleSignal("SIGTERM");
  process.once("SIGINT", handleInterrupt);
  process.once("SIGTERM", handleTermination);

  try {
    console.log("[eneo] Building the UI package for development...");
    const build = spawnBun(["run", "--cwd", "packages/ui", "build:dev"]);
    children.add(build);
    const buildExit = await waitForChild(build);
    children.delete(build);
    if (requestedSignal) return requestedSignal === "SIGINT" ? 130 : 143;
    if (buildExit.error || buildExit.code !== 0) {
      console.error(
        `[eneo] UI development build exited with code ${buildExit.code ?? 1}.`,
      );
      return buildExit.code ?? 1;
    }

    const postBuildStatus = await snapshotFrontendStatus();
    if (postBuildStatus.kind !== "starting") {
      printStatus(postBuildStatus);
      return postBuildStatus.kind === "conflict" ? 1 : 0;
    }

    console.log("[eneo] Starting the UI watcher and web frontend...");
    const ui = spawnBun(["run", "--cwd", "packages/ui", "dev"]);
    const web = spawnBun(["run", "--cwd", "apps/web", "dev"]);
    children.add(ui);
    children.add(web);
    const firstExit = await Promise.race([
      waitForChild(ui).then((exit) => ({ name: "UI watcher", exit })),
      waitForChild(web).then((exit) => ({ name: "web frontend", exit })),
    ]);
    if (requestedSignal) return requestedSignal === "SIGINT" ? 130 : 143;
    console.error(
      `[eneo] ${firstExit.name} stopped unexpectedly ` +
        `(code ${firstExit.exit.code ?? "none"}, signal ${firstExit.exit.signal ?? "none"}).`,
    );
    return firstExit.exit.code || 1;
  } finally {
    await terminateChildren(children);
    await clearLock(process.pid);
    process.off("SIGINT", handleInterrupt);
    process.off("SIGTERM", handleTermination);
  }
}

async function waitForStop() {
  const deadline = Date.now() + shutdownTimeoutMs;
  while (Date.now() < deadline) {
    const status = await snapshotFrontendStatus();
    if (status.kind === "stopped") return status;
    await delay(100);
  }
  return await snapshotFrontendStatus();
}

async function stopDevelopmentStack() {
  let status = await snapshotFrontendStatus();
  if (status.kind === "conflict") {
    printStatus(status);
    return 1;
  }
  if (status.kind === "stopped") {
    printStatus(status);
    return 0;
  }

  if (status.controllerPid) {
    console.log(
      `[eneo] Stopping frontend controller PID ${status.controllerPid}...`,
    );
    signalProcess(status.controllerPid, "SIGTERM");
  } else {
    console.log(
      `[eneo] Stopping same-checkout Vite process ${status.vitePids.join(", ")}...`,
    );
    for (const pid of status.vitePids) signalProcess(pid, "SIGTERM");
  }

  status = await waitForStop();
  if (status.kind === "running") {
    for (const pid of status.vitePids) signalProcess(pid, "SIGKILL");
  } else if (status.kind === "starting") {
    signalProcess(status.controllerPid, "SIGKILL");
  }
  status = await waitForStop();
  if (status.kind !== "stopped") {
    printStatus(status);
    return 1;
  }
  console.log("[eneo] Frontend stopped.");
  return 0;
}

async function main() {
  const command = process.argv[2] ?? "start";
  if (command === "status") {
    printStatus(await snapshotFrontendStatus());
    return 0;
  }
  if (command === "stop") return await stopDevelopmentStack();
  if (command === "start") return await runDevelopmentStack();
  if (command === "restart") {
    const stopCode = await stopDevelopmentStack();
    return stopCode === 0 ? await runDevelopmentStack() : stopCode;
  }
  console.error(
    `[eneo] Unknown dev command "${command}". Use start, status, stop, or restart.`,
  );
  return 1;
}

if (resolve(process.argv[1] ?? "") === scriptPath) {
  try {
    process.exitCode = await main();
  } catch (error) {
    console.error(
      `[eneo] Dev lifecycle failed: ${error instanceof Error ? error.message : error}`,
    );
    process.exitCode = 1;
  }
}
