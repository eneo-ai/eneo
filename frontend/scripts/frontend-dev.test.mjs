import { describe, expect, test } from "bun:test";

import {
  classifyFrontendStatus,
  isControllerProcess,
  isSameCheckoutViteProcess,
  parseProcessTable,
} from "./frontend-dev.mjs";

const workspaceRoot = "/workspace/frontend";
const controller = {
  pid: 41,
  parentPid: 1,
  command: "bun scripts/frontend-dev.mjs start",
  cwd: workspaceRoot,
};
const vite = {
  pid: 103,
  parentPid: 41,
  command:
    "node /workspace/frontend/apps/web/node_modules/.bin/vite dev --host",
};

describe("frontend dev process ownership", () => {
  test("parses process records without depending on command spacing", () => {
    expect(
      parseProcessTable(`
       41       1 bun scripts/frontend-dev.mjs start
      103      41 node /workspace/frontend/apps/web/node_modules/.bin/vite dev --host
    `),
    ).toEqual([
      { pid: 41, parentPid: 1, command: "bun scripts/frontend-dev.mjs start" },
      {
        pid: 103,
        parentPid: 41,
        command:
          "node /workspace/frontend/apps/web/node_modules/.bin/vite dev --host",
      },
    ]);
  });

  test("recognizes Vite only when it belongs to this checkout", () => {
    expect(isSameCheckoutViteProcess(vite, workspaceRoot)).toBe(true);
    expect(
      isSameCheckoutViteProcess(
        {
          ...vite,
          command:
            "node /workspace/another-app/node_modules/.bin/vite dev --host",
        },
        workspaceRoot,
      ),
    ).toBe(false);
  });

  test("requires both the controller command and checkout cwd", () => {
    expect(isControllerProcess(controller, workspaceRoot)).toBe(true);
    expect(
      isControllerProcess(
        { ...controller, cwd: "/workspace/another-app" },
        workspaceRoot,
      ),
    ).toBe(false);
    expect(
      isControllerProcess(
        { ...controller, command: "node another-app.js" },
        workspaceRoot,
      ),
    ).toBe(false);
  });
});

describe("frontend dev status", () => {
  test("reports a managed running frontend", () => {
    expect(
      classifyFrontendStatus({
        portOpen: true,
        processes: [controller, vite],
        controllerPid: controller.pid,
        workspaceRoot,
      }),
    ).toEqual({
      kind: "running",
      vitePids: [vite.pid],
      controllerPid: controller.pid,
    });
  });

  test("reports an existing direct Vite start as running but unmanaged", () => {
    expect(
      classifyFrontendStatus({
        portOpen: true,
        processes: [vite],
        controllerPid: undefined,
        workspaceRoot,
      }),
    ).toEqual({
      kind: "running",
      vitePids: [vite.pid],
      controllerPid: undefined,
    });
  });

  test("keeps startup explicit before Vite binds the port", () => {
    expect(
      classifyFrontendStatus({
        portOpen: false,
        processes: [controller],
        controllerPid: controller.pid,
        workspaceRoot,
      }),
    ).toEqual({ kind: "starting", controllerPid: controller.pid });
  });

  test("refuses ownership when another application occupies port 3000", () => {
    expect(
      classifyFrontendStatus({
        portOpen: true,
        processes: [
          { ...vite, command: "node /workspace/another-app/server.js" },
        ],
        controllerPid: undefined,
        workspaceRoot,
      }),
    ).toEqual({ kind: "conflict" });
  });

  test("reports stopped when neither an owner nor a listener remains", () => {
    expect(
      classifyFrontendStatus({
        portOpen: false,
        processes: [],
        controllerPid: undefined,
        workspaceRoot,
      }),
    ).toEqual({ kind: "stopped" });
  });
});
