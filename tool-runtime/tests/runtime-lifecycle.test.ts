import { createServer } from "node:http";
import { expect, test } from "bun:test";
import { createHandler } from "../src/server";
import { runIsolated } from "../src/sandbox";
import { work } from "../src/work";
import { ToolError } from "../src/errors";
import { computeConfigSchema } from "../src/tools/compute/config";
import { downloadFile } from "../src/tools/tabular/download";

const token = "x".repeat(40);
test("diagnostics are authenticated and discovery works while execution is occupied", async () => {
  let finish!: () => void;
  let entered!: () => void;
  const began = new Promise<void>((r) => {
    entered = r;
  });
  const handler = createHandler({
    token,
    maxConcurrency: 1,
    version: "2.3.0",
    revision: "a".repeat(40),
    confinement: { files: true, tcp: true },
    endpoints: [
      {
        slug: "compute",
        toolTimeoutMs: 10000,
        tools: [
          {
            name: "wait",
            title: "Wait",
            description: "",
            readOnly: true,
            inputSchema: {},
            execute: async () => {
              entered();
              await new Promise<void>((r) => {
                finish = r;
              });
              return { ok: true };
            },
          } as any,
        ],
      },
    ],
  });
  function rpc(method: string, params: unknown) {
    return handler(
      new Request("http://runtime/mcp/compute", {
        method: "POST",
        headers: {
          authorization: "Bearer " + token,
          "content-type": "application/json",
          accept: "application/json, text/event-stream",
        },
        body: JSON.stringify({ jsonrpc: "2.0", id: 1, method, params }),
      }),
    );
  }
  const running = rpc("tools/call", { name: "wait", arguments: {} });
  await began;
  expect((await rpc("tools/list", {})).status).toBe(200);
  expect((await handler(new Request("http://runtime/diagnostics"))).status).toBe(401);
  const response = await handler(
    new Request("http://runtime/diagnostics", { headers: { authorization: "Bearer " + token } }),
  );
  const status = (await response.json()) as any;
  expect(status.version).toBe("2.3.0");
  expect(status.execution.active).toBe(1);
  finish();
  await running;
});
test("abort kills an active child and returns cancellation", async () => {
  const controller = new AbortController();
  const pending = runIsolated(
    {
      job: { kind: "compute", code: "while(true) {}", input: null },
      config: { ...computeConfigSchema.parse({}), timeout_ms: 30000 },
    },
    30000,
    { signal: controller.signal },
  ).catch((e) => e);
  await Bun.sleep(100);
  controller.abort(new ToolError("CANCELLED", "cancel"));
  expect(await pending).toMatchObject({ code: "CANCELLED" });
});
test("download cancellation closes the pending request", async () => {
  const server = createServer((_request, _response) => {});
  await new Promise<void>((resolve) => server.listen(0, "127.0.0.1", resolve));
  const controller = new AbortController();
  try {
    const origin = "http://127.0.0.1:" + (server.address() as { port: number }).port;
    const pending = downloadFile(
      origin + "/file",
      {
        allowed_origins: [{ origin, allow_private: true }],
        max_upload_bytes: 1024,
        download_timeout_ms: 10000,
      },
      { signal: controller.signal },
    ).catch((e) => e);
    await Bun.sleep(20);
    controller.abort(new ToolError("CANCELLED", "cancel"));
    expect(await pending).toMatchObject({ code: "CANCELLED" });
  } finally {
    server.closeAllConnections();
    server.close();
  }
});

test("a whole-call deadline expires in admission and cancellation recovers capacity", async () => {
  let entered!: () => void;
  const began = new Promise<void>((resolve) => {
    entered = resolve;
  });
  let executed = 0;
  const endpoint = (slug: string, deadline: number) => ({
    slug,
    toolTimeoutMs: deadline,
    tools: [
      {
        name: "wait",
        title: "Wait",
        description: "",
        readOnly: true,
        inputSchema: {},
        execute: async () => {
          executed++;
          entered();
          const signal = work.getStore()!.signal;
          await new Promise<void>((_, reject) =>
            signal.addEventListener("abort", () => reject(signal.reason), { once: true }),
          );
          return {};
        },
      } as any,
    ],
  });
  const handler = createHandler({
    token,
    maxConcurrency: 1,
    maxQueue: 2,
    maxQueuePerGroup: 2,
    endpoints: [endpoint("long", 10000), endpoint("short", 30)],
  });
  const controller = new AbortController();
  const rpc = (slug: string, signal?: AbortSignal) =>
    handler(
      new Request("http://runtime/mcp/" + slug, {
        method: "POST",
        signal,
        headers: {
          authorization: "Bearer " + token,
          "content-type": "application/json",
          accept: "application/json, text/event-stream",
        },
        body: JSON.stringify({
          jsonrpc: "2.0",
          id: 1,
          method: "tools/call",
          params: { name: "wait", arguments: {} },
        }),
      }),
    );
  const running = rpc("long", controller.signal);
  await began;
  const response = (await (await rpc("short")).json()) as any;
  expect(response.result.isError).toBe(true);
  expect(response.result.content[0].text).toContain("TIMEOUT");
  expect(executed).toBe(1);
  controller.abort();
  await running;
  const diagnostic = (await (
    await handler(
      new Request("http://runtime/diagnostics", { headers: { authorization: "Bearer " + token } }),
    )
  ).json()) as any;
  expect(diagnostic.execution).toEqual({ active: 0, queued: 0 });
});
