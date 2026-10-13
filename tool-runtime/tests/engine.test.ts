import { describe, expect, test } from "bun:test";
import { mkdtemp, readFile, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { computeConfigSchema } from "../src/tools/compute/config";
import { runJavaScript } from "../src/tools/compute/engine/quickjs";
import type { ComputeExport } from "../src/tools/compute/ports";
import { asTabular, describeShape, labelOf, previewRows } from "../src/tools/compute/shape";

const config = computeConfigSchema.parse({});
const run = (code: string, input: unknown = null, overrides: Partial<typeof config> = {}) =>
  runJavaScript({ kind: "compute", code, input }, { ...config, ...overrides });
/** Runs with an export target in a fresh directory and returns the outcome and the CSV. */
async function runExport(
  code: string,
  target: Partial<Omit<ComputeExport, "outputPath">> = {},
  overrides: Partial<typeof config> = {},
) {
  const directory = await mkdtemp(join(tmpdir(), "eneo-engine-export-"));
  try {
    const outputPath = join(directory, "result.csv");
    const outcome = await runJavaScript(
      {
        kind: "compute",
        code,
        input: null,
        export: {
          outputPath,
          rowLimit: config.export_row_limit,
          maxBytes: config.max_export_bytes,
          ...target,
        },
      },
      { ...config, ...overrides },
    );
    const csv = await readFile(outputPath, "utf8").catch(() => undefined);
    return { outcome, csv };
  } finally {
    await rm(directory, { recursive: true, force: true });
  }
}

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

describe("labels", () => {
  test("identifiers read as words, keys that are words already stay as they are", () => {
    expect(labelOf("amount")).toBe("Amount");
    expect(labelOf("result_kr")).toBe("Result kr");
    expect(labelOf("interestRate")).toBe("Interest rate");
    expect(labelOf("saldo-vid-slut")).toBe("Saldo vid slut");
    expect(labelOf("ränta")).toBe("Ränta");
    expect(labelOf("År")).toBe("År");
    expect(labelOf("Ränta för året (kr)")).toBe("Ränta för året (kr)");
    expect(labelOf("2026")).toBe("2026");
    expect(labelOf("")).toBe("");
  });
});

describe("tabular export", () => {
  test("asTabular reads records with a union of keys and matrices with a header row", () => {
    expect(asTabular([{ a: 1, b: "x" }, { a: 2, c: true }])).toEqual({
      form: "records",
      columns: ["a", "b", "c"],
      rows: [
        [1, "x", null],
        [2, null, true],
      ],
    });
    expect(asTabular([["year", 2026], [1, 2], [3]])).toEqual({
      form: "matrix",
      columns: ["year", "2026"],
      rows: [
        [1, 2],
        [3, null],
      ],
    });
    expect(asTabular([["a", "b"]])).toEqual({ form: "matrix", columns: ["a", "b"], rows: [] });
    // Nested values stay as they are; the CSV writer renders them as JSON text.
    expect(asTabular([{ a: { n: 1 } }])!.rows).toEqual([[{ n: 1 }]]);
  });
  test("asTabular rejects what is not a table", () => {
    for (const value of [
      [],
      [1, 2],
      [{}],
      { a: 1 },
      "x",
      42,
      null,
      [{ a: 1 }, [1]],
      [["a"], [1, 2]],
      [[{ k: 1 }], [1]],
      [[], [1]],
    ])
      expect(asTabular(value)).toBeUndefined();
  });
  test("describeShape names the returned value for the error message", () => {
    expect(describeShape(42)).toBe("a number");
    expect(describeShape([1, 2, 3])).toBe("an array of 3 numbers");
    expect(describeShape(["x"])).toBe("an array of 1 string");
    expect(describeShape([1, "x"])).toBe("an array of 2 mixed values");
    expect(describeShape({ a: 1, b: 2 })).toBe("an object with 2 keys");
    expect(describeShape([])).toBe("an empty array");
    expect(describeShape(null)).toBe("null");
    expect(previewRows([["h"], [1], [2]], "matrix", 1)).toEqual([["h"], [1]]);
  });
  test("writes the table as CSV and keeps the first rows as a preview in the script's shape", async () => {
    const { outcome, csv } = await runExport(
      `return Array.from({ length: 30 }, (_, i) => ({ id: i + 1, name: "r" + i, note: i === 2 ? 'say "hi", twice' : null }));`,
    );
    expect(outcome.ok).toBe(true);
    expect(outcome.export).toEqual({
      columns: ["id", "name", "note"],
      rows: 30,
      truncated: false,
      preview_rows: 20,
    });
    const preview = outcome.result as Record<string, unknown>[];
    expect(preview).toHaveLength(20);
    expect(preview[0]).toEqual({ id: 1, name: "r0", note: null });
    const lines = csv!.split("\r\n");
    expect(lines[0]).toBe("id,name,note");
    expect(lines[3]).toBe('3,r2,"say ""hi"", twice"');
    expect(lines).toHaveLength(32); // header, 30 rows, trailing newline
  });
  test("a matrix keeps its header in the preview and pads short rows in the file", async () => {
    const { outcome, csv } = await runExport(`return [["a", "b"], [1, 2], [3]];`);
    expect(outcome.ok).toBe(true);
    expect(outcome.result).toEqual([["a", "b"], [1, 2], [3]]);
    expect(outcome.export).toMatchObject({ columns: ["a", "b"], rows: 2, preview_rows: 2 });
    expect(csv).toBe("a,b\r\n1,2\r\n3,\r\n");
  });
  test("a value that is not a table fails with a message the model can act on", async () => {
    const { outcome, csv } = await runExport("return 42;");
    expect(outcome.ok).toBe(false);
    expect(outcome.error).toMatchObject({ code: "RESULT_NOT_TABULAR" });
    expect(outcome.error!.message).toContain("The script returned a number");
    expect(outcome.error!.message).toContain("export=false");
    expect(csv).toBeUndefined();
  });
  test("stops at the row limit and says so", async () => {
    const { outcome, csv } = await runExport(
      `return Array.from({ length: 30 }, (_, i) => ({ id: i }));`,
      { rowLimit: 5 },
    );
    expect(outcome.export).toMatchObject({ rows: 5, truncated: true, preview_rows: 5 });
    expect(csv!.split("\r\n")).toHaveLength(7);
  });
  test("shrinks the preview until it fits the inline result limit", async () => {
    const { outcome } = await runExport(
      `return Array.from({ length: 30 }, (_, i) => ({ id: i, text: "x".repeat(200) }));`,
      {},
      { max_result_bytes: 1024 },
    );
    expect(outcome.ok).toBe(true);
    expect(outcome.export!.rows).toBe(30);
    expect(outcome.export!.preview_rows).toBeLessThan(20);
    expect(Buffer.byteLength(JSON.stringify(outcome.result))).toBeLessThanOrEqual(1024);
  });
  test("a value above the inline limit exports when it fits the export limit", async () => {
    const code = `return Array.from({ length: 50 }, (_, i) => ({ id: i, text: "y".repeat(100) }));`;
    const inline = await run(code, null, { max_result_bytes: 1024 });
    expect(inline.error).toMatchObject({ code: "RESULT_TOO_LARGE" });
    expect(inline.error!.message).toContain("export=true");
    const { outcome } = await runExport(code, {}, { max_result_bytes: 1024 });
    expect(outcome.ok).toBe(true);
    expect(outcome.export!.rows).toBe(50);
    const tooBig = await runExport(code, { maxBytes: 1024 }, { max_result_bytes: 1024 });
    expect(tooBig.outcome.error).toMatchObject({ code: "RESULT_TOO_LARGE" });
    expect(tooBig.outcome.error!.message).not.toContain("export=true");
  });
});

describe("prelude", () => {
  test("Decimal gives exact arithmetic and returns as a string", async () => {
    const outcome = await run(
      `return [new Decimal("0.1").plus("0.2").toString(), new Decimal(1234.5).times(1.12).toFixed(2), new Decimal("0.1").plus("0.2"), 0.1 + 0.2];`,
    );
    expect(outcome.ok).toBe(true);
    expect(outcome.result).toEqual(["0.3", "1382.64", "0.3", 0.30000000000000004]);
  });
  test("fmt formats numbers, percentages and dates the Swedish way", async () => {
    const outcome = await run(
      `return {
        a: fmt.number(1234.5, { decimals: 2 }), b: fmt.number(-1234567.891), c: fmt.number("1000"),
        d: fmt.number(new Decimal("2.5"), { decimals: 0 }), e: fmt.number(1e21), f: fmt.number(0.000001),
        g: fmt.percent(0.256), h: fmt.percent(1, 0), i: fmt.percent(-0.0005, 2),
        j: fmt.date("2026-10-13T22:30:00Z"), k: fmt.datetime(new Date(Date.UTC(2026, 0, 2, 9, 5))),
      };`,
    );
    expect(outcome.ok).toBe(true);
    expect(outcome.result).toEqual({
      a: "1\u00a0234,50",
      b: "-1\u00a0234\u00a0567,891",
      c: "1\u00a0000",
      d: "3",
      e: "1\u00a0000\u00a0000\u00a0000\u00a0000\u00a0000\u00a0000\u00a0000",
      f: "0,000001",
      g: "25,6\u00a0%",
      h: "100\u00a0%",
      i: "-0,05\u00a0%",
      j: "2026-10-13",
      k: "2026-01-02 09:05",
    });
    const bad = await run(`return fmt.number("abc");`);
    expect(bad.ok).toBe(false);
    expect(bad.error!.message).toContain("not a number");
  });
  test("the installed globals are hidden from enumeration and cannot be replaced or deleted", async () => {
    const outcome = await run(
      `const before = Object.keys(globalThis).sort();
       let replaced = "kept";
       try { globalThis.fmt = 1; replaced = typeof fmt === "number" ? "replaced" : "kept"; } catch { replaced = "threw"; }
       let deleted = "kept";
       try { deleted = delete globalThis.Decimal ? "deleted" : "kept"; } catch { deleted = "threw"; }
       let fmtMutated = "kept";
       try { fmt.number = () => "x"; fmtMutated = fmt.number(1) === "x" ? "mutated" : "kept"; } catch { fmtMutated = "threw"; }
       // A script may configure Decimal for its own run; the next call starts afresh.
       Decimal.set({ precision: 5 });
       return { before, replaced, deleted, fmtMutated, frozen: Object.isFrozen(fmt), third: new Decimal(1).div(3).toString() };`,
    );
    expect(outcome.ok).toBe(true);
    const result = outcome.result as Record<string, unknown>;
    expect(result.before as string[]).not.toContain("Decimal");
    expect(result.before as string[]).not.toContain("fmt");
    // Strict-mode scripts throw on these; a sloppy script just keeps what was there.
    expect(["kept", "threw"]).toContain(result.replaced as string);
    expect(["kept", "threw"]).toContain(result.deleted as string);
    expect(["kept", "threw"]).toContain(result.fmtMutated as string);
    expect(result.frozen).toBe(true);
    expect(result.third).toBe("0.33333");
    // The library default of 20 significant digits is back for the next call.
    expect((await run("return new Decimal(1).div(3).toString();")).result).toBe(
      "0.33333333333333333333",
    );
  });
  test("installing the prelude costs little of a call", async () => {
    const started = performance.now();
    for (let i = 0; i < 5; i++) expect((await run("return 1;")).ok).toBe(true);
    expect((performance.now() - started) / 5).toBeLessThan(50);
  });
});
