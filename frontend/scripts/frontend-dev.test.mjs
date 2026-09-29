import { describe, expect, test } from "bun:test";

import {
  classifyFrontendStatus,
  discoverOwnedProcessGroups,
  isControllerProcess,
  isOwnedProcessGroup,
  isSameCheckoutUiWatcherProcess,
  isSameCheckoutViteProcess,
  parseProcessTable,
} from "./frontend-dev.mjs";

const workspaceRoot = "/workspace/frontend";
const controller = {
  pid: 41,
  parentPid: 1,
  processGroupId: 41,
  command: "bun scripts/frontend-dev.mjs start",
  cwd: workspaceRoot,
};
const webGroup = { kind: "web", id: 102 };
const vite = {
  pid: 103,
  parentPid: webGroup.id,
  processGroupId: webGroup.id,
  command:
    "node /workspace/frontend/apps/web/node_modules/.bin/vite dev --host",
};
const uiGroup = { kind: "ui", id: 201 };
const uiWatcher = {
  pid: 202,
  parentPid: uiGroup.id,
  processGroupId: uiGroup.id,
  command:
    "node /workspace/frontend/packages/ui/node_modules/.bin/svelte-package --watch --preserve-output",
};

describe("frontend dev process ownership", () => {
  test("parses process records without depending on command spacing", () => {
    expect(
      parseProcessTable(`
       41       1      41 bun scripts/frontend-dev.mjs start
      103     102     102 node /workspace/frontend/apps/web/node_modules/.bin/vite dev --host
    `),
    ).toEqual([
      {
        pid: 41,
        parentPid: 1,
        processGroupId: 41,
        command: "bun scripts/frontend-dev.mjs start",
      },
      {
        pid: 103,
        parentPid: 102,
        processGroupId: 102,
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

  test("recognizes the UI watcher only when it belongs to this checkout", () => {
    expect(isSameCheckoutUiWatcherProcess(uiWatcher, workspaceRoot)).toBe(true);
    expect(
      isSameCheckoutUiWatcherProcess(
        {
          ...uiWatcher,
          command:
            "node /workspace/another-app/node_modules/.bin/svelte-package --watch",
        },
        workspaceRoot,
      ),
    ).toBe(false);
  });

  test("validates recorded groups against checkout-owned worker commands", () => {
    expect(isOwnedProcessGroup(webGroup, [vite], workspaceRoot)).toBe(true);
    expect(isOwnedProcessGroup(uiGroup, [uiWatcher], workspaceRoot)).toBe(true);
    expect(
      isOwnedProcessGroup(
        webGroup,
        [{ ...vite, command: "node /workspace/another-app/vite dev" }],
        workspaceRoot,
      ),
    ).toBe(false);
  });

  test("discovers an unrecorded checkout-owned group by command and cwd", () => {
    const groupLeader = {
      pid: uiGroup.id,
      parentPid: 41,
      processGroupId: uiGroup.id,
      command: "bun run --cwd packages/ui dev",
      cwd: workspaceRoot,
    };
    expect(discoverOwnedProcessGroups([groupLeader], workspaceRoot)).toEqual([
      uiGroup,
    ]);
    expect(
      discoverOwnedProcessGroups(
        [{ ...groupLeader, cwd: "/workspace/another-app" }],
        workspaceRoot,
      ),
    ).toEqual([]);
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
        processGroups: [webGroup],
        workspaceRoot,
      }),
    ).toEqual({
      kind: "running",
      vitePids: [vite.pid],
      uiWatcherPids: [],
      controllerPid: controller.pid,
      processGroups: [webGroup],
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
      uiWatcherPids: [],
      controllerPid: undefined,
      processGroups: [],
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
    ).toEqual({
      kind: "starting",
      controllerPid: controller.pid,
      processGroups: [],
      uiWatcherPids: [],
      vitePids: [],
    });
  });

  test("reports a UI watcher without its controller as orphaned", () => {
    expect(
      classifyFrontendStatus({
        portOpen: false,
        processes: [uiWatcher],
        controllerPid: undefined,
        processGroups: [uiGroup],
        workspaceRoot,
      }),
    ).toEqual({
      kind: "orphaned",
      processGroups: [uiGroup],
      uiWatcherPids: [uiWatcher.pid],
      vitePids: [],
    });
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
    ).toEqual({
      kind: "conflict",
      controllerPid: undefined,
      processGroups: [],
      uiWatcherPids: [],
      vitePids: [],
    });
  });

  test("reports a port conflict that appears while the controller builds", () => {
    expect(
      classifyFrontendStatus({
        portOpen: true,
        processes: [controller],
        controllerPid: controller.pid,
        workspaceRoot,
      }),
    ).toEqual({
      kind: "conflict",
      controllerPid: controller.pid,
      processGroups: [],
      uiWatcherPids: [],
      vitePids: [],
    });
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
