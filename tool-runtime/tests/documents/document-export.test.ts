import { describe, expect, test } from "bun:test";
import ExcelJS from "exceljs";
import { documentConfigSchema } from "../../src/tools/documents/config";
import { executeRender } from "../../src/tools/documents/execute";
import { contentDisposition, safeFilename } from "../../src/tools/documents/filename";
import { parseMarkdown, plainText } from "../../src/tools/documents/markdown/parse";
import { renderDocument } from "../../src/tools/documents/engine/render";
import { sheetName } from "../../src/tools/documents/engine/xlsx";
import type { RenderJob } from "../../src/tools/documents/ports";
import { documentTools, fileRenderer, spreadsheetTools } from "../../src/tools/documents/tool";
import { runIsolated } from "../../src/sandbox";
import { RichResult, type CallContext } from "../../src/tools/types";

const context: CallContext = { tenantId: "", userId: "" };
const SAMPLE = `# Tjänsteskrivelse

Inledning med **fet**, *kursiv*, \`kod\` och en [länk](https://example.org/a) samt [farlig](javascript:alert(1)).

## Förslag

1. Första
2. Andra
   - Underpunkt
     - Djupare

> Ett citat.

| Kolumn | Värde |
|---|---:|
| a | 1 |
| b & c | 2 |

\`\`\`sql
SELECT 1;
\`\`\`

---

![Bild av torget](https://example.org/x.png)

<!-- pagebreak -->

### Slut

<script>alert("x")</script>
`;
async function unzipText(buffer: Buffer, name: string): Promise<string> {
  const workbook = new ExcelJS.Workbook();
  // exceljs bundles jszip; borrow it to read arbitrary zip entries.
  const JSZip = (await import("jszip")).default;
  const zip = await JSZip.loadAsync(buffer);
  void workbook;
  return (await zip.file(name)?.async("string")) ?? "";
}

describe("markdown", () => {
  test("maps every supported construct and neutralises links, images and html", () => {
    const blocks = parseMarkdown(SAMPLE);
    expect(blocks.map((b) => b.type)).toEqual([
      "heading",
      "paragraph",
      "heading",
      "list",
      "quote",
      "table",
      "code",
      "hr",
      "paragraph",
      "pagebreak",
      "heading",
      "paragraph",
    ]);
    const intro = blocks[1] as Extract<
      ReturnType<typeof parseMarkdown>[number],
      { type: "paragraph" }
    >;
    expect(intro.runs.find((r) => r.bold)?.text).toBe("fet");
    expect(intro.runs.find((r) => r.code)?.text).toBe("kod");
    expect(intro.runs.find((r) => r.link)?.link).toBe("https://example.org/a");
    expect(intro.runs.find((r) => r.text === "farlig")?.link).toBeUndefined();
    const list = blocks[3] as Extract<ReturnType<typeof parseMarkdown>[number], { type: "list" }>;
    expect(list.ordered).toBe(true);
    expect(list.items[1]!.children[0]!.type).toBe("list");
    const table = blocks[5] as Extract<ReturnType<typeof parseMarkdown>[number], { type: "table" }>;
    expect(plainText(table.rows[1]![0]!)).toBe("b & c");
    expect(table.align).toEqual([null, "right"]);
    const image = blocks[8] as Extract<
      ReturnType<typeof parseMarkdown>[number],
      { type: "paragraph" }
    >;
    expect(image.runs[0]).toMatchObject({ text: "Bild av torget", italic: true });
    const html = blocks[11] as Extract<
      ReturnType<typeof parseMarkdown>[number],
      { type: "paragraph" }
    >;
    expect(plainText(html.runs)).toContain("<script>");
  });
  test("caps nesting and table width and never fetches anything", () => {
    const original = globalThis.fetch;
    let fetched = false;
    globalThis.fetch = (async () => {
      fetched = true;
      return new Response("");
    }) as unknown as typeof fetch;
    try {
      const deep = parseMarkdown("- a\n  - b\n    - c\n      - d\n        - e\n          - f\n");
      let block = deep[0]!;
      let depth = 0;
      while (block.type === "list") {
        depth++;
        const next = block.items[0]!.children[0];
        if (!next) break;
        block = next;
      }
      expect(depth).toBeLessThanOrEqual(4);
      const wide = parseMarkdown(
        `|${"h|".repeat(20)}\n|${"---|".repeat(20)}\n|${"c|".repeat(20)}\n`,
      );
      expect((wide[0] as { header: unknown[] }).header).toHaveLength(16);
      const big = "x".repeat(50_000);
      const started = performance.now();
      parseMarkdown(`# T\n\n${big}\n\n${"- item\n".repeat(2000)}`);
      expect(performance.now() - started).toBeLessThan(5000);
    } finally {
      globalThis.fetch = original;
    }
    expect(fetched).toBe(false);
  });
});
describe("filenames", () => {
  test("sanitises names and builds a safe disposition", () => {
    expect(safeFilename("Tjänsteskrivelse: trygghet/2026?.docx", "docx")).toBe(
      "Tjänsteskrivelse trygghet2026.docx",
    );
    expect(safeFilename('../..\\x\r\ny"z', "pdf")).toBe("xyz.pdf");
    expect(safeFilename("   ", "xlsx")).toBe("dokument.xlsx");
    expect(safeFilename("a".repeat(200), "docx")).toHaveLength(105);
    expect(contentDisposition("Rapport åäö.docx")).toBe(
      "attachment; filename=\"Rapport ___.docx\"; filename*=UTF-8''Rapport%20%C3%A5%C3%A4%C3%B6.docx",
    );
    expect(contentDisposition('a";b.pdf')).not.toContain('";b');
  });
});
describe("engines", () => {
  const document = {
    kind: "markdown" as const,
    title: "Rapport",
    content: SAMPLE,
    language: "sv" as const,
  };
  test("docx contains the text, escapes markup and carries a page break", async () => {
    const { buffer } = await renderDocument("docx", document, { organisationName: "Kommunen" });
    expect(buffer.subarray(0, 2).toString("hex")).toBe("504b");
    const xml = await unzipText(buffer, "word/document.xml");
    expect(xml).toContain("Tjänsteskrivelse");
    expect(xml).toContain("b &amp; c");
    expect(xml).toContain("&lt;script&gt;");
    expect(xml).not.toContain("<script>");
    expect(xml).toContain('w:type="page"');
    expect(xml).toContain("SELECT 1;");
    const rels = await unzipText(buffer, "word/_rels/document.xml.rels");
    expect(rels).toContain("https://example.org/a");
    expect(rels).not.toContain("javascript:");
    const core = await unzipText(buffer, "docProps/core.xml");
    expect(core).toContain("Kommunen");
  });
  test("xlsx keeps strings as strings, numbers numeric and names unique", async () => {
    const { buffer } = await renderDocument("xlsx", {
      kind: "sheets",
      title: "Data",
      sheets: [
        {
          name: "Bad/Name?",
          columns: ["a", "b"],
          rows: [
            ["=1+1", 2],
            ["x", null],
            [true, 3.5],
          ],
        },
        { name: "Bad Name", columns: ["c"], rows: [] },
      ],
    });
    const workbook = new ExcelJS.Workbook();
    await workbook.xlsx.load(buffer as unknown as ArrayBuffer);
    expect(workbook.worksheets.map((w) => w.name)).toEqual(["Bad Name", "Bad Name (2)"]);
    const sheet = workbook.worksheets[0]!;
    expect(sheet.getCell("A2").value).toBe("=1+1");
    expect(sheet.getCell("A2").type).toBe(ExcelJS.ValueType.String);
    expect(sheet.getCell("B2").value).toBe(2);
    expect(sheet.getCell("B3").value).toBeNull();
    expect(sheet.getCell("A1").font?.bold).toBe(true);
    expect(sheet.views[0]?.state).toBe("frozen");
    const taken = new Set<string>();
    expect(sheetName("x".repeat(40), taken)).toHaveLength(31);
    expect(sheetName("x".repeat(40), taken)).toEndWith(" (2)");
  });
  test("pdf embeds DejaVu, numbers pages and starts with the magic bytes", async () => {
    const { buffer, pages } = await renderDocument("pdf", document, {
      organisationName: "Kommunen",
    });
    expect(buffer.subarray(0, 5).toString()).toBe("%PDF-");
    expect(buffer.includes(Buffer.from("DejaVuSans"))).toBe(true);
    expect(pages).toBeGreaterThanOrEqual(2);
  });
  test("refuses mismatched specs", async () => {
    await expect(renderDocument("xlsx", document)).rejects.toThrow("needs sheets");
  });
});
describe("tools", () => {
  const config = documentConfigSchema.parse({ organisation_name: "Kommunen" });
  const requests: RenderJob[] = [];
  const render = fileRenderer(async (job) => {
    requests.push(job);
    return executeRender(job);
  });
  const tools = Object.fromEntries(
    [...documentTools(config, render), ...spreadsheetTools(config, render)].map((t) => [t.name, t]),
  );

  test("returns the document as an embedded resource with a sanitised name", async () => {
    const result = await tools.create_document!.execute(
      { title: "Rapport: Q3/2026", content: "# Hej\n\nText.", format: "docx" },
      context,
    );
    expect(result).toBeInstanceOf(RichResult);
    const { structured, files } = result as RichResult;
    expect(structured).toMatchObject({ filename: "Rapport Q32026.docx", format: "docx" });
    expect(structured).not.toHaveProperty("download_url");
    const [file] = files;
    expect(file!.mimeType).toBe(
      "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    );
    expect(file!.uri).toEndWith("/Rapport%20Q32026.docx");
    expect(Buffer.from(file!.blob, "base64").subarray(0, 2).toString()).toBe("PK");
    expect(requests.at(-1)).toMatchObject({
      kind: "render_document",
      format: "docx",
      organisationName: "Kommunen",
      document: { kind: "markdown", title: "Rapport: Q3/2026", language: "sv" },
    });
  });

  test("spreadsheets come back as typed workbooks", async () => {
    const result = (await tools.create_spreadsheet!.execute(
      { title: "Tabell", sheets: [{ name: "Blad", columns: ["a", "b"], rows: [["=1", 2]] }] },
      context,
    )) as RichResult;
    const workbook = new ExcelJS.Workbook();
    await workbook.xlsx.load(
      Buffer.from(result.files[0]!.blob, "base64") as unknown as ArrayBuffer,
    );
    const sheet = workbook.worksheets[0]!;
    expect(sheet.getCell("A2").type).toBe(ExcelJS.ValueType.String);
    expect(sheet.getCell("B2").value).toBe(2);
  });

  test("the documents endpoint offers only document formats", async () => {
    await expect(
      tools.create_document!.execute({ title: "x", content: "y", format: "xlsx" }, context),
    ).rejects.toThrow();
  });

  test("oversized output is refused", async () => {
    await expect(
      render({
        format: "pdf",
        document: { kind: "markdown", title: "Stor", content: "Text", language: "sv" },
        maxBytes: 1000,
      }),
    ).rejects.toMatchObject({ code: "EXPORT_TOO_LARGE" });
  });

  test("renders in a sandbox child through a parent-owned output file", async () => {
    const childRender = fileRenderer(
      async (job) => (await runIsolated({ job }, 25_000)) as { bytes: number; pages?: number },
    );
    const { buffer, pages } = await childRender({
      format: "pdf",
      document: { kind: "markdown", title: "Barn", content: "Hej", language: "sv" },
      maxBytes: config.max_export_bytes,
    });
    expect(buffer.subarray(0, 5).toString()).toBe("%PDF-");
    expect(pages).toBe(1);
  });
});
