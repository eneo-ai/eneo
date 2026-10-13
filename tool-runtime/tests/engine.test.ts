import { describe, expect, test } from "bun:test";
import { computeConfigSchema } from "../src/tools/compute/config";
import { runJavaScript } from "../src/tools/compute/engine/quickjs";

const config = computeConfigSchema.parse({});
const run = (code: string, input: unknown = null, overrides: Partial<typeof config> = {}) =>
  runJavaScript({ kind: "compute", code, input }, { ...config, ...overrides });

describe("sandbox engine", () => {
  test("returns the value of return, exposes input and captures console output", async () => {
    const outcome = await run(
      `console.log("rows", input.rows.length, { ok: true });
       const total = input.rows.reduce((sum, r) => sum + r.value, 0);
       console.warn("done");
       return { total, mean: total / input.rows.length, names: input.rows.map((r) => r.name) };`,
      {
        rows: [
          { name: "a", value: 10 },
          { name: "b", value: 20 },
        ],
      },
    );
    expect(outcome.ok).toBe(true);
    expect(outcome.result).toEqual({ total: 30, mean: 15, names: ["a", "b"] });
    expect(outcome.logs).toEqual(['rows 2 {"ok":true}', "done"]);
    expect(outcome.dropped_log_lines).toBe(0);
    expect(outcome.duration_ms).toBeGreaterThanOrEqual(0);
  });
  test("supports await and modern syntax and maps undefined to null", async () => {
    const outcome = await run(
      `const doubled = await Promise.all([1, 2, 3].map(async (n) => n * 2));
       const { a = 1, ...rest } = { b: 2, c: 3 };
       return [doubled, a, rest, [1, 2, 3].at(-1), Object.hasOwn(rest, "b")];`,
    );
    expect(outcome.ok).toBe(true);
    expect(outcome.result).toEqual([[2, 4, 6], 1, { b: 2, c: 3 }, 3, true]);
    expect((await run("console.log('no return')")).result).toBeNull();
  });
  test("exposes no host capabilities", async () => {
    const outcome = await run(
      `return {
        fetch: typeof fetch, require: typeof require, process: typeof process,
        timers: typeof setTimeout, bun: typeof Bun, imports: typeof importScripts,
        input_type: typeof input,
      };`,
    );
    expect(outcome.result).toEqual({
      fetch: "undefined",
      require: "undefined",
      process: "undefined",
      timers: "undefined",
      bun: "undefined",
      imports: "undefined",
      input_type: "object",
    });
    const dynamicImport = await run(`return await import("node:fs");`);
    expect(dynamicImport.ok).toBe(false);
  });
  test("reports syntax and runtime errors with the script line", async () => {
    const syntax = await run("const x = ;");
    expect(syntax.ok).toBe(false);
    expect(syntax.error?.code).toBe("SYNTAX_ERROR");
    const thrown = await run(`console.log("before");\nthrow new RangeError("too big");`);
    expect(thrown.ok).toBe(false);
    expect(thrown.error).toMatchObject({
      code: "RUNTIME_ERROR",
      name: "RangeError",
      message: "too big",
      line: 2,
    });
    expect(thrown.logs).toEqual(["before"]);
    const rejected = await run(`await Promise.reject(new Error("later"));`);
    expect(rejected.error).toMatchObject({ code: "RUNTIME_ERROR", message: "later" });
    const undefinedCall = await run("return input.missing.deeper;", {});
    expect(undefinedCall.error?.code).toBe("RUNTIME_ERROR");
  });
  test("stops infinite loops, runaway memory and deep recursion", async () => {
    const loop = await run("while (true) {}", null, { timeout_ms: 200 });
    expect(loop.error?.code).toBe("TIMEOUT");
    expect(loop.duration_ms).toBeLessThan(5000);
    const memory = await run("const a = []; while (true) a.push(new Array(1e5).fill(1));", null, {
      memory_mb: 16,
    });
    expect(memory.error?.code).toBe("OUT_OF_MEMORY");
    const recursion = await run("function f(n) { return f(n + 1) + 1; } return f(0);");
    expect(recursion.ok).toBe(false);
    expect(recursion.error?.name).toBe("RangeError");
  });
  test("rejects promises that can never settle instead of hanging", async () => {
    const outcome = await run("await new Promise(() => {}); return 1;");
    expect(outcome.error?.code).toBe("UNSETTLED_PROMISE");
  });
  test("bounds result size, log lines and non-serialisable values", async () => {
    const large = await run("return 'x'.repeat(5000);", null, { max_result_bytes: 1024 });
    expect(large.error?.code).toBe("RESULT_TOO_LARGE");
    const noisy = await run(
      "for (let i = 0; i < 10; i++) console.log(i, 'y'.repeat(2000));",
      null,
      {
        max_log_lines: 3,
      },
    );
    expect(noisy.ok).toBe(true);
    expect(noisy.logs).toHaveLength(3);
    expect(noisy.logs[0]!.length).toBeLessThanOrEqual(1001);
    expect(noisy.dropped_log_lines).toBe(7);
    const cyclic = await run("const o = {}; o.self = o; return o;");
    expect(cyclic.error?.code).toBe("RESULT_NOT_SERIALIZABLE");
    const bigint = await run("return 10n ** 20n;");
    expect(bigint.error?.code).toBe("RESULT_NOT_SERIALIZABLE");
    const fn = await run("return () => 1;");
    expect(fn.result).toBeNull();
  });
  test("runs are independent", async () => {
    await run("globalThis.leak = 42;");
    const next = await run("return typeof leak;");
    expect(next.result).toBe("undefined");
  });
});
