import { describe, expect, test } from "bun:test";
import { Document, Packer, Paragraph } from "docx";
import JSZip from "jszip";
import { createHandler } from "../../src/server";
import { documentControlRenderer } from "../../src/tools/documents/control";
import { executeRender } from "../../src/tools/documents/execute";
import { fileRenderer } from "../../src/tools/documents/tool";
import { inspectPdf } from "./pdf-inspect";

const token = "private-backend-token".repeat(3);
const renderDocument = documentControlRenderer(fileRenderer(executeRender), 10 * 1024 * 1024);
const handler = createHandler({ token, endpoints: [], maxConcurrency: 2, renderDocument });
const body = {
  mode: "render",
  format: "docx",
  title: "Rapport",
  content: "# Resultat\n\n**Beslut**\n\n| Namn | Antal |\n| --- | --- |\n| Åsa | 3 |",
};
function request(payload: unknown = body, headers: Record<string, string> = {}) {
  return handler(
    new Request("http://runtime/documents/render", {
      method: "POST",
      headers: { authorization: `Bearer ${token}`, "content-type": "application/json", ...headers },
      body: JSON.stringify(payload),
    }),
  );
}

describe("deterministic backend document control", () => {
  test("renders readable structured Word with the native shared engine", async () => {
    const response = await request();
    expect(response.status).toBe(200);
    expect(response.headers.get("cache-control")).toBe("no-store");
    const zip = await JSZip.loadAsync(await response.arrayBuffer());
    const xml = await zip.file("word/document.xml")!.async("string");
    expect(xml).toContain("Resultat");
    expect(xml).toContain("Åsa");
    expect(xml).toContain("<w:tbl>");
    expect(xml).toContain("<w:b/>");
  });
  test("renders PDF with title, language and semantic structure", async () => {
    const response = await request({ ...body, format: "pdf", language: "sv" });
    expect(response.status).toBe(200);
    const facts = await inspectPdf(Buffer.from(await response.arrayBuffer()));
    expect(facts.pages).toBeGreaterThan(0);
    expect(facts.structured).toBe(true);
    expect(facts.lang).toBe("sv-SE");
  });
  test("fills a supplied template without a model call", async () => {
    const template = await Packer.toBuffer(
      new Document({ sections: [{ children: [new Paragraph("Kund: {{customer}}")] }] }),
    );
    const response = await request({
      mode: "fill",
      format: "docx",
      template: template.toString("base64"),
      values: { customer: "Åsa & Bo" },
    });
    expect(response.status).toBe(200);
    const zip = await JSZip.loadAsync(await response.arrayBuffer());
    const xml = await zip.file("word/document.xml")!.async("string");
    expect(xml).toContain("Åsa &amp; Bo");
    expect(xml).not.toContain("{{customer}}");
  });
  test("requires the backend bearer and refuses browser-origin calls", async () => {
    expect((await request(body, { authorization: "Bearer wrong" })).status).toBe(401);
    expect((await request(body, { origin: "https://eneo.example" })).status).toBe(403);
  });
  test("refuses paths, URLs, oversized content and noncanonical templates", async () => {
    for (const invalid of [
      { ...body, template: "http://internal/secret" },
      { ...body, template: "eA==\n" },
      { ...body, path: "/etc/passwd" },
      { ...body, content: "x".repeat(1_000_001) },
      { mode: "fill", format: "pdf", template: "eA==", values: {} },
    ])
      expect((await request(invalid)).status).toBe(422);
  });
});
