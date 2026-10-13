import { describe, expect, test } from "bun:test";
import { writeFile } from "node:fs/promises";
import { computeConfigSchema } from "../../src/tools/compute/config";
import { runJavaScript } from "../../src/tools/compute/engine/quickjs";
import type { ComputeExecutor } from "../../src/tools/compute/tool";
import { computeTools } from "../../src/tools/compute/tool";
import { RichResult } from "../../src/tools/types";

const config = computeConfigSchema.parse({});
const ctx = { tenantId: "tenant", userId: "user" };
const inProcess: ComputeExecutor = (job) => runJavaScript(job, config);
const tool = (run: ComputeExecutor = inProcess) => computeTools(config, run)[0]!;
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
