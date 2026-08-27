import { execFile, spawn } from "node:child_process";
import {
  mkdir,
  readdir,
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
const configuredTestPort = Number(
  process.env.NODE_ENV === "test"
    ? process.env.ENEO_FRONTEND_DEV_TEST_PORT
    : undefined,
);
const frontendPort =
  Number.isInteger(configuredTestPort) && configuredTestPort > 0
    ? configuredTestPort
    : 3000;
const frontendUrl = `http://localhost:${frontendPort}`;
const shutdownTimeoutMs = 5_000;
const processGroupArguments = {
  build: "run --cwd packages/ui build:dev",
  ui: "run --cwd packages/ui dev",
  web: "run --cwd apps/web dev",
};
const processGroupKinds = new Set(Object.keys(processGroupArguments));

export function parseProcessTable(output) {
  return output
    .split("\n")
    .map((line) => line.match(/^\s*(\d+)\s+(\d+)\s+(\d+)\s+(.*)$/))
    .filter((match) => match !== null)
    .map((match) => ({
      pid: Number(match[1]),
      parentPid: Number(match[2]),
      processGroupId: Number(match[3]),
      command: match[4],
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

export function isSameCheckoutUiWatcherProcess(processRecord, workspaceRoot) {
  const watcherEntrypoint = join(
    workspaceRoot,
    "packages",
    "ui",
    "node_modules",
    ".bin",
    "svelte-package",
  );
  return (
    processRecord.command.includes(watcherEntrypoint) &&
    /(?:^|\s)--watch(?:\s|$)/.test(processRecord.command)
  );
}

export function isControllerProcess(processRecord, workspaceRoot) {
  const absoluteScriptPath = join(workspaceRoot, "scripts", "frontend-dev.mjs");
  const runsController =
    processRecord.command.includes(absoluteScriptPath) ||
    processRecord.command.includes("scripts/frontend-dev.mjs");
  return runsController && processRecord.cwd === workspaceRoot;
}

function isExpectedProcessGroupLeader(
  processRecord,
  processGroup,
  workspaceRoot,
) {
  if (
    processRecord.pid !== processGroup.id ||
    processRecord.processGroupId !== processGroup.id ||
    processRecord.cwd !== workspaceRoot
  ) {
    return false;
  }

  return processRecord.command.includes(
    processGroupArguments[processGroup.kind],
  );
}

function inferProcessGroupKind(processRecord) {
  if (processRecord.pid !== processRecord.processGroupId) return undefined;
  return Object.entries(processGroupArguments).find(([, expectedArguments]) =>
    processRecord.command.includes(expectedArguments),
  )?.[0];
}

export function discoverOwnedProcessGroups(processes, workspaceRoot) {
  return processes
    .map((processRecord) => ({
      processRecord,
      kind: inferProcessGroupKind(processRecord),
    }))
    .filter(
      ({ processRecord, kind }) => kind && processRecord.cwd === workspaceRoot,
    )
    .map(({ processRecord, kind }) => ({
      kind,
      id: processRecord.processGroupId,
    }));
}

export function isOwnedProcessGroup(processGroup, processes, workspaceRoot) {
  const groupProcesses = processes.filter(
    (processRecord) => processRecord.processGroupId === processGroup.id,
  );
  if (
    groupProcesses.some((processRecord) =>
      isExpectedProcessGroupLeader(processRecord, processGroup, workspaceRoot),
    )
  ) {
    return true;
  }
  if (processGroup.kind === "web") {
    return groupProcesses.some((processRecord) =>
      isSameCheckoutViteProcess(processRecord, workspaceRoot),
    );
  }
  if (processGroup.kind === "ui") {
    return groupProcesses.some((processRecord) =>
      isSameCheckoutUiWatcherProcess(processRecord, workspaceRoot),
    );
  }
  return false;
}

export function classifyFrontendStatus({
  portOpen,
  processes,
  controllerPid,
  processGroups = [],
  workspaceRoot,
}) {
  const vitePids = processes
    .filter((processRecord) =>
      isSameCheckoutViteProcess(processRecord, workspaceRoot),
    )
    .map((processRecord) => processRecord.pid);
  const uiWatcherPids = processes
    .filter((processRecord) =>
      isSameCheckoutUiWatcherProcess(processRecord, workspaceRoot),
    )
    .map((processRecord) => processRecord.pid);

  if (
    vitePids.length > 0 ||
    processGroups.some((processGroup) => processGroup.kind === "web")
  ) {
    return {
      kind: "running",
      vitePids,
      uiWatcherPids,
      controllerPid,
      processGroups,
    };
  }
  if (portOpen) {
    return {
      kind: "conflict",
      controllerPid,
      processGroups,
      uiWatcherPids,
      vitePids,
    };
  }
  if (controllerPid) {
    return {
      kind: "starting",
      controllerPid,
      processGroups,
      uiWatcherPids,
      vitePids,
    };
  }
  if (processGroups.length > 0 || uiWatcherPids.length > 0) {
    return {
      kind: "orphaned",
      processGroups,
      uiWatcherPids,
      vitePids,
    };
  }
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

function processGroupPath(processGroup) {
  return join(lockDirectory, `group-${processGroup.kind}-${processGroup.id}`);
}

async function readRecordedProcessGroups() {
  let entries;
  try {
    entries = await readdir(lockDirectory);
  } catch (error) {
    if (error?.code === "ENOENT") return [];
    throw error;
  }

  return entries
    .map((entry) => entry.match(/^group-([a-z]+)-(\d+)$/))
    .filter(
      (match) =>
        match !== null &&
        processGroupKinds.has(match[1]) &&
        Number(match[2]) > 0,
    )
    .map((match) => ({ kind: match[1], id: Number(match[2]) }));
}

async function readLockState() {
  const [controllerPid, processGroups] = await Promise.all([
    readLockOwner(),
    readRecordedProcessGroups(),
  ]);
  return { controllerPid, processGroups };
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

async function readProcesses(lockState) {
  const { stdout } = await execFileAsync(
    "ps",
    ["-axo", "pid=,ppid=,pgid=,command="],
    {
      maxBuffer: 4 * 1024 * 1024,
    },
  );
  const processes = parseProcessTable(stdout);
  const cwdPids = new Set(
    [
      lockState.controllerPid,
      ...lockState.processGroups.map((processGroup) => processGroup.id),
    ].filter(Boolean),
  );
  for (const processRecord of processes) {
    if (inferProcessGroupKind(processRecord)) cwdPids.add(processRecord.pid);
  }
  await Promise.all(
    processes
      .filter((processRecord) => cwdPids.has(processRecord.pid))
      .map(async (processRecord) => {
        processRecord.cwd = await readProcessCwd(processRecord.pid);
      }),
  );
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
  const lockState = await readLockState();
  if (expectedPid && lockState.controllerPid !== expectedPid) return;
  let entries;
  try {
    entries = await readdir(lockDirectory);
  } catch (error) {
    if (error?.code === "ENOENT") return;
    throw error;
  }
  for (const entry of entries) {
    try {
      await unlink(join(lockDirectory, entry));
    } catch (error) {
      if (error?.code !== "ENOENT") throw error;
    }
  }
  try {
    await rmdir(lockDirectory);
  } catch (error) {
    if (error?.code !== "ENOENT" && error?.code !== "ENOTEMPTY") throw error;
  }
}

async function removeLockOwner(expectedPid) {
  if ((await readLockOwner()) !== expectedPid) return;
  try {
    await unlink(lockOwnerPath);
  } catch (error) {
    if (error?.code !== "ENOENT") throw error;
  }
}

async function recordProcessGroup(kind, child) {
  if (!child.pid) throw new Error(`Could not determine ${kind} process PID.`);
  if ((await readLockOwner()) !== process.pid) {
    throw new Error("Frontend controller lost ownership of its lock.");
  }
  const processGroup = { kind, id: child.pid };
  await writeFile(processGroupPath(processGroup), `${child.pid}\n`, {
    flag: "wx",
    mode: 0o600,
  });
  return processGroup;
}

async function removeRecordedProcessGroup(processGroup) {
  try {
    await unlink(processGroupPath(processGroup));
  } catch (error) {
    if (error?.code !== "ENOENT") throw error;
  }
}

async function snapshotFrontendStatus() {
  const lockState = await readLockState();
  const [processes, portOpen] = await Promise.all([
    readProcesses(lockState),
    isPortOpen(),
  ]);
  const controller = processes.find(
    (processRecord) =>
      processRecord.pid === lockState.controllerPid &&
      isControllerProcess(processRecord, frontendRoot),
  );
  const processGroups = lockState.processGroups.filter((processGroup) =>
    isOwnedProcessGroup(processGroup, processes, frontendRoot),
  );
  const recordedGroupIds = new Set(
    processGroups.map((processGroup) => processGroup.id),
  );
  processGroups.push(
    ...discoverOwnedProcessGroups(processes, frontendRoot).filter(
      (processGroup) => !recordedGroupIds.has(processGroup.id),
    ),
  );

  if (!controller && lockState.controllerPid) {
    await removeLockOwner(lockState.controllerPid);
  }
  if (!controller) {
    const ownedGroupPaths = new Set(processGroups.map(processGroupPath));
    await Promise.all(
      lockState.processGroups
        .filter(
          (processGroup) =>
            !ownedGroupPaths.has(processGroupPath(processGroup)),
        )
        .map(removeRecordedProcessGroup),
    );
    if (lockState.controllerPid || lockState.processGroups.length > 0) {
      if (processGroups.length === 0) await clearLock();
    }
  }

  return classifyFrontendStatus({
    portOpen,
    processes,
    controllerPid: controller?.pid,
    processGroups,
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
          '[eneo] Frontend workers are running without their controller. Run "bun run dev:restart" to recover them.',
        );
      }
      return;
    case "starting":
      console.log(
        `[eneo] Frontend is starting (controller PID ${status.controllerPid}).`,
      );
      return;
    case "orphaned":
      console.log(
        "[eneo] Frontend workers are running without their controller.",
      );
      console.log(
        '[eneo] Run "bun run dev:stop" or "bun run dev:restart" to recover them.',
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
  for (let attempt = 0; attempt < 3; attempt += 1) {
    try {
      await mkdir(lockDirectory);
      await writeFile(lockOwnerPath, `${process.pid}\n`, {
        flag: "wx",
        mode: 0o600,
      });
      return true;
    } catch (error) {
      if (error?.code !== "EEXIST") throw error;
      let status = await snapshotFrontendStatus();
      if (status.kind !== "stopped") return false;
      await delay(50);
      status = await snapshotFrontendStatus();
      if (status.kind !== "stopped") return false;
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
    return initialStatus.kind === "conflict" ||
      initialStatus.kind === "orphaned"
      ? 1
      : 0;
  }
  if (!(await acquireLock())) {
    const status = await snapshotFrontendStatus();
    printStatus(status);
    return status.kind === "conflict" || status.kind === "orphaned" ? 1 : 0;
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
    const buildGroup = await recordProcessGroup("build", build);
    const buildExit = await waitForChild(build);
    children.delete(build);
    await removeRecordedProcessGroup(buildGroup);
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
    children.add(ui);
    await recordProcessGroup("ui", ui);
    const web = spawnBun(["run", "--cwd", "apps/web", "dev"]);
    children.add(web);
    await recordProcessGroup("web", web);
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

function hasCheckoutProcesses(status) {
  return Boolean(
    status.controllerPid ||
    status.processGroups?.length ||
    status.vitePids?.length ||
    status.uiWatcherPids?.length,
  );
}

function signalCheckoutProcesses(status, signal, controllerOnly = false) {
  if (status.controllerPid) {
    signalProcess(status.controllerPid, signal);
    if (controllerOnly) return;
  }
  for (const processGroup of status.processGroups ?? []) {
    signalProcess(processGroup.id, signal, true);
  }
  for (const pid of status.vitePids ?? []) signalProcess(pid, signal);
  for (const pid of status.uiWatcherPids ?? []) signalProcess(pid, signal);
}

async function waitForCheckoutStop() {
  const deadline = Date.now() + shutdownTimeoutMs;
  while (Date.now() < deadline) {
    const status = await snapshotFrontendStatus();
    if (!hasCheckoutProcesses(status)) return status;
    await delay(100);
  }
  return await snapshotFrontendStatus();
}

async function stopDevelopmentStack() {
  let status = await snapshotFrontendStatus();
  if (status.kind === "conflict" && !hasCheckoutProcesses(status)) {
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
    signalCheckoutProcesses(status, "SIGTERM", true);
  } else {
    const groupIds = (status.processGroups ?? []).map(
      (processGroup) => processGroup.id,
    );
    console.log(
      `[eneo] Stopping checkout-owned frontend workers ${[
        ...groupIds,
        ...(status.vitePids ?? []),
        ...(status.uiWatcherPids ?? []),
      ].join(", ")}...`,
    );
    signalCheckoutProcesses(status, "SIGTERM");
  }

  status = await waitForCheckoutStop();
  if (hasCheckoutProcesses(status)) {
    signalCheckoutProcesses(status, "SIGKILL");
  }
  status = await waitForCheckoutStop();
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
