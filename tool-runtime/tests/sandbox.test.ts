import { describe, expect, test } from "bun:test";
import { computeConfigSchema } from "../src/tools/compute/config";
import { runIsolated } from "../src/sandbox";

const config = computeConfigSchema.parse({});

describe("sandbox child", () => {
  test("inherits no environment beyond PATH and its private TMPDIR", async () => {
    process.env.TOOL_RUNTIME_TOKEN = "must-not-leak-into-the-child-process";
    try {
      const result = await runIsolated({ job: { kind: "env" } }, 10_000);
      const names = (result.names as string[]).filter((n) => !["PATH", "TMPDIR"].includes(n));
      // Bun may add its own runtime markers; none of the parent's variables may appear.
      expect(names.filter((n) => n in process.env)).toEqual([]);
      expect(result.names).not.toContain("TOOL_RUNTIME_TOKEN");
    } finally {
      delete process.env.TOOL_RUNTIME_TOKEN;
    }
  });

  test("runs a compute job and returns the outcome", async () => {
    const outcome = await runIsolated(
      {
        job: { kind: "compute", code: "return input.a * input.b;", input: { a: 6, b: 7 } },
        config,
      },
      10_000,
    );
    expect(outcome).toMatchObject({ ok: true, result: 42 });
  });

  test("the guest cannot reach host APIs even inside the child", async () => {
    const outcome = await runIsolated(
      {
        job: {
          kind: "compute",
          code: `return [typeof fetch, typeof process, typeof Bun, typeof require, Object.keys(globalThis).sort()];`,
          input: null,
        },
        config,
      },
      10_000,
    );
    const [fetchType, processType, bunType, requireType, globals] = outcome.result as [
      string,
      string,
      string,
      string,
      string[],
    ];
    expect([fetchType, processType, bunType, requireType]).toEqual([
      "undefined",
      "undefined",
      "undefined",
      "undefined",
    ]);
    expect(globals).toContain("input");
    expect(globals).not.toContain("process");
  });

  test("kills a child that outlives the whole-job deadline", async () => {
    // A script deadline above the job deadline: only the parent's kill can stop it.
    const started = performance.now();
    await expect(
      runIsolated(
        {
          job: { kind: "compute", code: "while (true) {}", input: null },
          config: { ...config, timeout_ms: 30_000 },
        },
        1_500,
      ),
    ).rejects.toMatchObject({ code: "TIMEOUT" });
    expect(performance.now() - started).toBeLessThan(5_000);
  });
});
