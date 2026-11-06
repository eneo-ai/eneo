import { afterAll, describe, expect, test } from "bun:test";
import ExcelJS from "exceljs";
import JSZip from "jszip";
import { mkdtemp, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { readSource } from "../../src/tools/documents/sources";

const directory = await mkdtemp(join(tmpdir(), "sources-test-"));
afterAll(() => rm(directory, { recursive: true, force: true }));

describe("source files", () => {
  test("keep dates and timestamps in ISO form, whatever the host's time zone", async () => {
    const path = join(directory, "dates.csv");
    await writeFile(path, "Datum,Tid\n2026-09-01,2026-09-02 12:30:00\n");
    const { rows } = await readSource({ index: 0, path, isXlsx: false });
    expect(rows).toEqual([["2026-09-01", "2026-09-02T12:30:00.000Z"]]);
  });

  async function read(bytes: Buffer | Uint8Array, sheet?: string) {
    const path = join(directory, `${crypto.randomUUID()}.xlsx`);
    await writeFile(path, bytes);
    return readSource({ index: 0, path, isXlsx: true, ...(sheet ? { sheet } : {}) });
  }

  async function workbook(sheets: Record<string, string[][]>) {
    const book = new ExcelJS.Workbook();
    for (const [name, rows] of Object.entries(sheets)) book.addWorksheet(name).addRows(rows);
    return Buffer.from(await book.xlsx.writeBuffer());
  }

  test.each([
    ["a plain zip", async () => new JSZip().file("notes.txt", "hej").generateAsync({ type: "nodebuffer" })],
    ["a workbook whose parts are broken", async () => {
      const zip = await JSZip.loadAsync(await workbook({ Data: [["a"], ["1"]] }));
      zip.file("xl/workbook.xml", "<not a workbook");
      return zip.generateAsync({ type: "nodebuffer" });
    }],
    ["a cut-off archive", async () => (await workbook({ Data: [["a"], ["1"]] })).subarray(0, 200)],
  ])("refuse %s named .xlsx as a bad file, not an operator's problem", async (_case, bytes) => {
    await expect(read(await bytes())).rejects.toMatchObject({ code: "INVALID_FILE" });
  });

  test("name the sheets with data when the one asked for is not among them", async () => {
    const bytes = await workbook({ Data: [["a"], ["1"]], Tom: [], Mer: [["b"], ["2"]] });
    const refused = await read(bytes, "Nej").catch((error) => error);
    expect(refused.code).toBe("UNKNOWN_SHEET");
    expect(refused.message).toContain('"Nej"');
    expect(refused.message).toContain("Data, Mer");
    // A sheet that exists but holds nothing is not one to choose either.
    expect((await read(bytes, "Tom").catch((error) => error)).message).toContain("Data, Mer");
  });

  test.each([[undefined], ["Tom"]])("say that a workbook has no data (sheet %s)", async (sheet) => {
    const refused = await read(await workbook({ Tom: [] }), sheet).catch((error) => error);
    expect(refused.code).toBe("INVALID_FILE");
    expect(refused.message).toContain("no data");
  });
});
