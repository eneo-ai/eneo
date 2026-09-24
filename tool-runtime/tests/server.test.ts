import { describe, expect, test } from "bun:test";
import { loadConfig } from "../src/config";
import { createHandler } from "../src/server";
import { computeConfigSchema } from "../src/tools/compute/config";
import { runJavaScript } from "../src/tools/compute/engine/quickjs";
import type { ComputeJob } from "../src/tools/compute/ports";
import { computeTools } from "../src/tools/compute/tool";

const TOKEN = "t".repeat(40);
const compute = computeConfigSchema.parse({ max_code_chars: 200, max_input_bytes: 1024 });
const jobs: ComputeJob[] = [];
const handler = createHandler({
  token: TOKEN,
  maxConcurrency: 4,
  toolTimeoutMs: 10_000,
  endpoints: [
    {
      slug: "compute",
      // In-process engine: the sandbox boundary has its own tests.
      tools: computeTools(compute, async (job) => {
        jobs.push(job);
        return runJavaScript(job, compute);
      }),
    },
  ],
});

let id = 0;
function rpc(method: string, params: unknown, headers: Record<string, string> = {}) {
  return handler(
    new Request("http://tool-runtime:3010/mcp/compute", {
      method: "POST",
      headers: {
        authorization: `Bearer ${TOKEN}`,
        "content-type": "application/json",
        accept: "application/json, text/event-stream",
        ...headers,
      },
      body: JSON.stringify({ jsonrpc: "2.0", id: ++id, method, params }),
    }),
  );
}
async function callTool(args: unknown) {
  const response = await rpc("tools/call", { name: "run_javascript", arguments: args });
  expect(response.status).toBe(200);
  return ((await response.json()) as { result: Record<string, unknown> }).result;
}

describe("authentication", () => {
  test("rejects missing, wrong and differently-sized tokens", async () => {
    for (const authorization of [
      "",
      "Bearer ",
      `Bearer ${TOKEN}x`,
      `Basic ${TOKEN}`,
      "Bearer nope",
    ]) {
      const response = await rpc("tools/list", {}, { authorization });
      expect(response.status).toBe(401);
    }
  });
  test("refuses browser requests", async () => {
    const response = await rpc("tools/list", {}, { origin: "https://evil.example" });
    expect(response.status).toBe(403);
  });
  test("unknown endpoints are 404 before authentication", async () => {
    const response = await handler(
      new Request("http://tool-runtime:3010/mcp/tabular", { method: "POST" }),
    );
    expect(response.status).toBe(404);
  });
  test("health needs no token", async () => {
    const response = await handler(new Request("http://tool-runtime:3010/health/ready"));
    expect(response.status).toBe(200);
  });
  test("the runtime refuses to start with a short token", () => {
    expect(() => loadConfig({ TOOL_RUNTIME_TOKEN: "short" })).toThrow();
    expect(loadConfig({ TOOL_RUNTIME_TOKEN: TOKEN }).port).toBe(3010);
  });
});

describe("MCP endpoint", () => {
  test("lists run_javascript as a read-only tool", async () => {
    const response = await rpc("tools/list", {});
    expect(response.status).toBe(200);
    const body = (await response.json()) as { result: { tools: Array<Record<string, unknown>> } };
    expect(body.result.tools.map((t) => t.name)).toEqual(["run_javascript"]);
    expect(body.result.tools[0]!.annotations).toMatchObject({
      readOnlyHint: true,
      openWorldHint: false,
    });
  });
  test("computes an exact result from JSON input", async () => {
    const result = await callTool({
      code: "const s = [...input].sort((a, b) => a - b); return { sum: s.reduce((a, b) => a + b, 0), median: (s[1] + s[2]) / 2 };",
      input: [1200.5, 99.25, 450, 3000],
    });
    expect(result.structuredContent).toMatchObject({
      ok: true,
      result: { sum: 4749.75, median: 825.25 },
    });
    expect(jobs.at(-1)).toMatchObject({ kind: "compute" });
  });
  test("script failures come back as ok=false results", async () => {
    const result = await callTool({ code: "throw new Error('boom');" });
    expect(result.isError).toBeUndefined();
    expect(result.structuredContent).toMatchObject({ ok: false, error: { code: "RUNTIME_ERROR" } });
  });
  test("oversized code and input are tool errors", async () => {
    const tooLong = await callTool({ code: "x".repeat(201) });
    expect(tooLong.isError).toBe(true);
    const bigInput = await callTool({ code: "return 1;", input: "y".repeat(2000) });
    expect(bigInput.isError).toBe(true);
    expect(JSON.stringify(bigInput.content)).toContain("INPUT_TOO_LARGE");
  });
  test("rejects oversized request bodies", async () => {
    const response = await handler(
      new Request("http://tool-runtime:3010/mcp/compute", {
        method: "POST",
        headers: { authorization: `Bearer ${TOKEN}`, "content-type": "application/json" },
        body: JSON.stringify({ padding: "z".repeat(300 * 1024) }),
      }),
    );
    expect(response.status).toBe(413);
  });
});
