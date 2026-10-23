import { describe, expect, test } from "bun:test";
import { writeFile } from "node:fs/promises";
import { computeConfigSchema } from "../../src/tools/compute/config";
import { runJavaScript } from "../../src/tools/compute/engine/quickjs";
import { showsResult } from "../../src/tools/compute/shape";
import type { ComputeExecutor } from "../../src/tools/compute/tool";
import { EXPORT_SHOWN, TABLE_SHOWN, VALUE_SHOWN, computeTools } from "../../src/tools/compute/tool";
import { computeResultView } from "../../src/tools/compute/view";
import { RichResult, type ToolView } from "../../src/tools/types";

const config = computeConfigSchema.parse({});
const ctx = { tenantId: "tenant", userId: "user" };
const inProcess: ComputeExecutor = (job) => runJavaScript(job, config);
const stubView: ToolView = { uri: "ui://compute/test", html: "<html></html>" };
const tool = (run: ComputeExecutor = inProcess, view?: ToolView) =>
  computeTools(config, run, view)[0]!;
const rows = `return Array.from({ length: 30 }, (_, i) => ({ år: 2000 + i, belopp: i * 1.5 }));`;

describe("run_javascript", () => {
  test("returns the value inline by default", async () => {
    const result = await tool().execute({ code: "return input.a + input.b;", input: { a: 1, b: 2 } }, ctx);
    expect(result).not.toBeInstanceOf(RichResult);
    expect(result).toMatchObject({ ok: true, result: 3, logs: [] });
  });

  test("attaches the table as a CSV file when exporting", async () => {
    const result = await tool().execute({ code: rows, export: true }, ctx);
    expect(result).toBeInstanceOf(RichResult);
    const { structured, files, images } = result as RichResult;
    expect(images).toEqual([]);
    expect(files).toHaveLength(1);
    expect(files[0]!.mimeType).toBe("text/csv");
    expect(files[0]!.uri).toMatch(
      /^eneo-tool-runtime:\/\/compute\/[0-9a-f-]{36}\/resultat\.csv$/,
    );
    const csv = Buffer.from(files[0]!.blob, "base64").toString("utf8");
    expect(csv.split("\r\n")[0]).toBe("år,belopp");
    expect(csv.split("\r\n")).toHaveLength(32);
    expect(structured.export).toMatchObject({
      filename: "resultat.csv",
      columns: ["år", "belopp"],
      rows: 30,
      preview_rows: 20,
      truncated: false,
    });
    expect(String(structured.export && (structured.export as { delivered: string }).delivered)).toContain(
      "reference url",
    );
    expect(structured.result).toHaveLength(20);
    expect(structured.shown).toBeUndefined();
  });

  test("names the file after export_filename, never a path", async () => {
    const result = (await tool().execute(
      { code: rows, export: true, export_filename: "Ränta/2026.csv" },
      ctx,
    )) as RichResult;
    expect(result.structured.export).toMatchObject({ filename: "Ränta2026.csv" });
    expect(result.files[0]!.uri.endsWith(`/${encodeURIComponent("Ränta2026.csv")}`)).toBe(true);
  });

  test("a non-tabular value under export is an ordinary failed result without a file", async () => {
    const result = await tool().execute({ code: "return 42;", export: true }, ctx);
    expect(result).not.toBeInstanceOf(RichResult);
    expect(result).toMatchObject({ ok: false, error: { code: "RESULT_NOT_TABULAR" } });
  });

  test("refuses an export above the file size limit", async () => {
    const oversized: ComputeExecutor = async (job) => {
      await writeFile(job.export!.outputPath, Buffer.alloc(20 * 1024 * 1024 + 1, 0x61));
      return {
        ok: true,
        result: [],
        logs: [],
        dropped_log_lines: 0,
        duration_ms: 1,
        export: { columns: ["a"], rows: 1, truncated: false, preview_rows: 0 },
      };
    };
    await expect(tool(oversized).execute({ code: "return [];", export: true }, ctx)).rejects.toMatchObject({
      code: "EXPORT_TOO_LARGE",
    });
  });

  test("rejects an oversized input before running anything", async () => {
    let ran = false;
    const spy: ComputeExecutor = async () => {
      ran = true;
      return { ok: true, result: null, logs: [], dropped_log_lines: 0, duration_ms: 0 };
    };
    await expect(
      tool(spy).execute({ code: "return 1;", input: "x".repeat(config.max_input_bytes + 1) }, ctx),
    ).rejects.toMatchObject({ code: "INPUT_TOO_LARGE" });
    expect(ran).toBe(false);
  });
});

describe("result view", () => {
  const table = `return [{ a: 1 }, { a: 2 }, { a: 3 }];`;
  const scalar = `return 42;`;
  const viewed = { ...ctx, showsViews: true };

  test("the tool brings the built view and declares what it asks of the browser", async () => {
    const view = await computeResultView();
    expect(view.uri).toMatch(/^ui:\/\/compute\/compute-result-[0-9a-f]{12}\.html$/);
    expect(view.ui).toEqual({ prefersBorder: true, permissions: { clipboardWrite: {} } });
    expect(view.html).toContain("<script");
    expect(view.html).not.toMatch(/<script[^>]+src=/);
    expect(Buffer.byteLength(view.html)).toBeLessThan(2 * 1024 * 1024);
    expect(tool(inProcess, view).view).toBe(view);
    expect(tool().view).toBeUndefined();
  });

  test("a table of several rows is shown unasked; a scalar only when the model asks", async () => {
    const shown = async (code: string, args: Record<string, unknown> = {}) =>
      ((await tool(inProcess, stubView).execute({ code, ...args }, viewed)) as Record<string, unknown>)
        .shown;
    expect(await shown(table)).toBe(TABLE_SHOWN);
    expect(await shown(table, { display: "result" })).toBe(TABLE_SHOWN);
    expect(await shown(scalar)).toBeUndefined();
    expect(await shown(scalar, { display: "result" })).toBe(VALUE_SHOWN);
    expect(await shown(`return { a: 1 };`, { display: "result" })).toBe(VALUE_SHOWN);
    expect(await shown(`return [{ a: 1 }];`)).toBeUndefined();
  });

  test("an exported table is shown as a preview, with its own hint", async () => {
    const run = tool(inProcess, stubView);
    const exported = (await run.execute({ code: table, export: true }, viewed)) as RichResult;
    expect(exported.structured.shown).toBe(EXPORT_SHOWN);
  });

  test("nothing is shown for display=none, a failure, or a host without views", async () => {
    const run = tool(inProcess, stubView);
    expect(await run.execute({ code: table, display: "none" }, viewed)).not.toHaveProperty("shown");
    expect(await run.execute({ code: "throw new Error('x');", display: "result" }, viewed)).toMatchObject({
      ok: false,
    });
    expect(await run.execute({ code: "throw new Error('x');", display: "result" }, viewed)).not.toHaveProperty(
      "shown",
    );
    expect(await run.execute({ code: table }, ctx)).not.toHaveProperty("shown");
    expect(await run.execute({ code: table }, { ...ctx, showsViews: false })).not.toHaveProperty("shown");
    expect(await tool().execute({ code: table }, viewed)).not.toHaveProperty("shown");
  });

  test("the view decides what to draw with the same rule the tool used", () => {
    const value = [{ a: 1 }, { a: 2 }];
    expect(showsResult({ ok: true, result: value, exported: false, display: "auto" })).toBe("table");
    expect(showsResult({ ok: true, result: value, exported: true, display: "auto" })).toBe("table");
    expect(showsResult({ ok: true, result: value, exported: false, display: "none" })).toBe(false);
    expect(showsResult({ ok: false, result: value, exported: false, display: "result" })).toBe(false);
    expect(showsResult({ ok: true, result: 1, exported: false, display: "auto" })).toBe(false);
    expect(showsResult({ ok: true, result: 1, exported: false, display: "result" })).toBe("value");
    expect(showsResult({ ok: true, result: [{ a: 1 }], exported: false, display: "result" })).toBe(
      "value",
    );
  });

  test("the result names its display mode for the view", async () => {
    expect(await tool().execute({ code: scalar }, ctx)).toMatchObject({ display: "auto" });
    expect(await tool().execute({ code: scalar, display: "none" }, ctx)).toMatchObject({
      display: "none",
    });
  });
});
