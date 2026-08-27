import { spawn } from "node:child_process";
import {
  chmod,
  copyFile,
  mkdir,
  mkdtemp,
  readFile,
  readdir,
  rm,
  writeFile,
} from "node:fs/promises";
import { createServer } from "node:net";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

import { expect, test } from "bun:test";

const sourceDirectory = dirname(fileURLToPath(import.meta.url));
const controllerSourcePath = join(sourceDirectory, "frontend-dev.mjs");
const fakeBunSourcePath = join(
  sourceDirectory,
  "fixtures",
  "frontend-dev-fake-bun.mjs",
);
const processBoundaryTest = process.platform === "win32" ? test.skip : test;

function isProcessAlive(pid) {
  try {
    process.kill(pid, 0);
    return true;
  } catch (error) {
    if (error?.code === "ESRCH") return false;
    throw error;
  }
}

async function waitFor(predicate, description, timeoutMs = 10_000) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    if (await predicate()) return;
    await Bun.sleep(50);
  }
  throw new Error(`Timed out waiting for ${description}.`);
}

async function waitForExit(child, timeoutMs = 10_000) {
  if (child.exitCode !== null || child.signalCode !== null) {
    return { code: child.exitCode, signal: child.signalCode };
  }
  return await new Promise((resolveExit, rejectExit) => {
    const timeout = setTimeout(() => {
      child.off("exit", handleExit);
      rejectExit(new Error(`Process ${child.pid} did not exit.`));
    }, timeoutMs);
    const handleExit = (code, signal) => {
      clearTimeout(timeout);
      resolveExit({ code, signal });
    };
    child.once("exit", handleExit);
  });
}

async function findUnusedPort() {
  const server = createServer();
  await new Promise((resolveListen, rejectListen) => {
    server.once("error", rejectListen);
    server.listen(0, "127.0.0.1", resolveListen);
  });
  const address = server.address();
  const port = typeof address === "object" && address ? address.port : null;
  await new Promise((resolveClose) => server.close(resolveClose));
  if (!port) throw new Error("Could not allocate a fixture port.");
  return port;
}

async function createFixture() {
  const root = await mkdtemp(join(tmpdir(), "eneo-frontend-dev-"));
  const scriptsDirectory = join(root, "scripts");
  const fakeBinDirectory = join(root, "fixture-bin");
  const eventsPath = join(root, "events.log");
  const controllerPath = join(scriptsDirectory, "frontend-dev.mjs");
  const lockDirectory = join(
    root,
    "node_modules",
    ".cache",
    "eneo",
    "frontend-dev.lock",
  );
  await Promise.all([
    mkdir(scriptsDirectory, { recursive: true }),
    mkdir(fakeBinDirectory, { recursive: true }),
  ]);
  await copyFile(controllerSourcePath, controllerPath);

  const fakeBunPath = join(fakeBinDirectory, "bun");
  const fakeBunSource = await readFile(fakeBunSourcePath, "utf8");
  await writeFile(fakeBunPath, `#!${process.execPath}\n${fakeBunSource}`);
  await chmod(fakeBunPath, 0o755);
  await writeFile(eventsPath, "");
  await writeFile(
    join(scriptsDirectory, "record-clean.mjs"),
    `import { appendFileSync } from "node:fs";\nappendFileSync(process.env.ENEO_FRONTEND_DEV_FIXTURE_EVENTS, \`clean:start:\${process.pid}\\n\`);\n`,
  );
  await writeFile(
    join(root, "package.json"),
    `${JSON.stringify(
      {
        private: true,
        scripts: {
          dev: "bun scripts/frontend-dev.mjs start",
          "dev:stop": "bun scripts/frontend-dev.mjs stop",
          "dev:restart": "bun scripts/frontend-dev.mjs restart",
          "dev:clean": "bun run dev:stop && bun run clean:cache && bun run dev",
          "clean:cache": "bun scripts/record-clean.mjs",
        },
      },
      null,
      2,
    )}\n`,
  );

  const port = await findUnusedPort();
  return {
    root,
    controllerPath,
    eventsPath,
    lockDirectory,
    env: {
      ...process.env,
      PATH: `${fakeBinDirectory}:${process.env.PATH ?? ""}`,
      NODE_ENV: "test",
      ENEO_FRONTEND_DEV_FIXTURE_EVENTS: eventsPath,
      ENEO_FRONTEND_DEV_TEST_PORT: String(port),
    },
  };
}

function spawnLifecycle(fixture, command) {
  return spawn(process.execPath, [fixture.controllerPath, command], {
    cwd: fixture.root,
    env: fixture.env,
    stdio: "ignore",
  });
}

function spawnPackageScript(fixture, script) {
  return spawn(process.execPath, ["run", script], {
    cwd: fixture.root,
    env: fixture.env,
    stdio: "ignore",
  });
}

async function runLifecycle(fixture, command) {
  const result = await waitForExit(spawnLifecycle(fixture, command), 15_000);
  expect(result).toEqual({ code: 0, signal: null });
}

async function readEvents(fixture) {
  const contents = await readFile(fixture.eventsPath, "utf8");
  return contents.trim().split("\n").filter(Boolean);
}

async function startedPids(fixture, kind) {
  const prefix = `${kind}:start:`;
  return (await readEvents(fixture))
    .filter((event) => event.startsWith(prefix))
    .map((event) => Number(event.slice(prefix.length)));
}

async function readControllerPid(fixture) {
  return Number(
    (await readFile(join(fixture.lockDirectory, "owner"), "utf8")).trim(),
  );
}

async function waitForManagedStack(fixture, expectedStarts) {
  await waitFor(async () => {
    const [events, lockEntries] = await Promise.all([
      readEvents(fixture),
      readdir(fixture.lockDirectory).catch(() => []),
    ]);
    return (
      events.filter((event) => event.startsWith("ui:start:")).length ===
        expectedStarts &&
      events.filter((event) => event.startsWith("web:start:")).length ===
        expectedStarts &&
      lockEntries.some((entry) => entry.startsWith("group-ui-")) &&
      lockEntries.some((entry) => entry.startsWith("group-web-"))
    );
  }, `managed stack start ${expectedStarts}`);
}

async function killController(controller) {
  process.kill(controller.pid, "SIGKILL");
  await waitForExit(controller);
}

async function expectProcessesStopped(pids) {
  await waitFor(
    () => pids.every((pid) => !isProcessAlive(pid)),
    `processes ${pids.join(", ")} to stop`,
  );
}

async function cleanupFixture(fixture, spawnedProcesses) {
  try {
    await runLifecycle(fixture, "stop");
  } catch {
    // Best-effort cleanup below handles a partially initialized fixture.
  }

  const workerPids = [
    ...(await startedPids(fixture, "ui")),
    ...(await startedPids(fixture, "web")),
  ];
  for (const pid of workerPids) {
    if (!isProcessAlive(pid)) continue;
    try {
      process.kill(-pid, "SIGKILL");
    } catch (error) {
      if (error?.code !== "ESRCH") throw error;
    }
  }
  for (const child of spawnedProcesses) {
    if (child.exitCode !== null || child.signalCode !== null) continue;
    try {
      child.kill("SIGKILL");
    } catch (error) {
      if (error?.code !== "ESRCH") throw error;
    }
  }
  await rm(fixture.root, { recursive: true, force: true });
}

processBoundaryTest(
  "dev:clean replaces a running controller and both worker groups",
  async () => {
    const fixture = await createFixture();
    const spawnedProcesses = [];
    try {
      const originalController = spawnLifecycle(fixture, "start");
      spawnedProcesses.push(originalController);
      await waitForManagedStack(fixture, 1);
      const originalControllerPid = await readControllerPid(fixture);
      const originalWorkerPids = [
        ...(await startedPids(fixture, "ui")),
        ...(await startedPids(fixture, "web")),
      ];

      const cleanCommand = spawnPackageScript(fixture, "dev:clean");
      spawnedProcesses.push(cleanCommand);
      await waitForManagedStack(fixture, 2);

      const replacementControllerPid = await readControllerPid(fixture);
      expect(replacementControllerPid).not.toBe(originalControllerPid);
      await expectProcessesStopped([
        originalControllerPid,
        ...originalWorkerPids,
      ]);
      expect((await startedPids(fixture, "build")).length).toBe(2);
      expect(
        (await readEvents(fixture)).filter((event) =>
          event.startsWith("clean:start:"),
        ),
      ).toHaveLength(1);

      const currentUiPids = await startedPids(fixture, "ui");
      const currentWebPids = await startedPids(fixture, "web");
      expect(currentUiPids).toHaveLength(2);
      expect(currentWebPids).toHaveLength(2);
      expect(isProcessAlive(currentUiPids[1])).toBe(true);
      expect(isProcessAlive(currentWebPids[1])).toBe(true);
    } finally {
      await cleanupFixture(fixture, spawnedProcesses);
    }
  },
  30_000,
);

processBoundaryTest(
  "stop removes both worker groups after the controller is killed",
  async () => {
    const fixture = await createFixture();
    const spawnedProcesses = [];
    try {
      const controller = spawnLifecycle(fixture, "start");
      spawnedProcesses.push(controller);
      await waitForManagedStack(fixture, 1);
      const workerPids = [
        ...(await startedPids(fixture, "ui")),
        ...(await startedPids(fixture, "web")),
      ];
      await killController(controller);
      expect(workerPids.every(isProcessAlive)).toBe(true);

      await runLifecycle(fixture, "stop");
      await expectProcessesStopped(workerPids);
      await expect(readdir(fixture.lockDirectory)).rejects.toMatchObject({
        code: "ENOENT",
      });
    } finally {
      await cleanupFixture(fixture, spawnedProcesses);
    }
  },
  30_000,
);

processBoundaryTest(
  "restart replaces orphaned groups with exactly one new worker pair",
  async () => {
    const fixture = await createFixture();
    const spawnedProcesses = [];
    try {
      const originalController = spawnLifecycle(fixture, "start");
      spawnedProcesses.push(originalController);
      await waitForManagedStack(fixture, 1);
      const originalWorkerPids = [
        ...(await startedPids(fixture, "ui")),
        ...(await startedPids(fixture, "web")),
      ];
      await killController(originalController);

      const restartController = spawnLifecycle(fixture, "restart");
      spawnedProcesses.push(restartController);
      await waitForManagedStack(fixture, 2);
      await expectProcessesStopped(originalWorkerPids);

      const uiPids = await startedPids(fixture, "ui");
      const webPids = await startedPids(fixture, "web");
      expect(uiPids.slice(1).filter(isProcessAlive)).toHaveLength(1);
      expect(webPids.slice(1).filter(isProcessAlive)).toHaveLength(1);
      expect(await readControllerPid(fixture)).toBe(restartController.pid);
    } finally {
      await cleanupFixture(fixture, spawnedProcesses);
    }
  },
  30_000,
);
