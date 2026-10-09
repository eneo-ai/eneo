import { describe, expect, test } from "bun:test";
import { Document, Footer, Header, ImageRun, Packer, Paragraph, TextRun, PageNumber } from "docx";
import { renderHtml } from "../../src/tools/documents/engine/html";
import { fontStack, pdfProfile, profileCss } from "../../src/tools/documents/engine/pdf-profile";
import { pdfAvailable } from "../../src/tools/documents/engine/pdf";
import { renderDocument } from "../../src/tools/documents/engine/render";
import { renderIntoTemplate } from "../../src/tools/documents/engine/word/apply";
import { builtinTemplate } from "../../src/tools/documents/engine/word/builtin";
import { parseMarkdown } from "../../src/tools/documents/markdown/parse";
import { inspectPdf } from "./pdf-inspect";
import { mkdtemp } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";

// A 1x1 PNG, enough for a logo.
const PNG = Buffer.from(
  "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg==",
  "base64",
);

/** A municipal letterhead: Arial body, blue Cambria headings, a logo and page numbers. */
async function letterhead(): Promise<Buffer> {
  return Buffer.from(
    await Packer.toBuffer(
      new Document({
        styles: {
          default: {
            document: {
              run: { font: "Arial", size: 20 },
              paragraph: { spacing: { after: 120, line: 276 } },
            },
          },
          paragraphStyles: [
            {
              id: "Heading1",
              name: "heading 1",
              basedOn: "Normal",
              run: { font: "Cambria", size: 32, bold: true, color: "1F4E79" },
              paragraph: { spacing: { before: 360, after: 120 } },
            },
          ],
        },
        sections: [
          {
            properties: {
              page: {
                size: { width: 11906, height: 16838 },
                margin: { top: 2268, right: 1134, bottom: 1701, left: 1701, header: 567, footer: 567 },
              },
            },
            headers: {
              default: new Header({
                children: [
                  new Paragraph({
                    children: [
                      new ImageRun({
                        type: "png",
                        data: PNG,
                        transformation: { width: 120, height: 40 },
                        altText: { name: "logo", description: "Kommunens logotyp", title: "logo" },
                      }),
                    ],
                  }),
                  new Paragraph({ children: [new TextRun("Dnr {{dnr}}")] }),
                ],
              }),
            },
            footers: {
              default: new Footer({
                children: [
                  new Paragraph({
                    children: [
                      new TextRun({ text: "{{organisation}}", size: 16 }),
                      new TextRun({ text: "\tSida ", size: 16 }),
                      new TextRun({ children: [PageNumber.CURRENT], size: 16 }),
                      new TextRun({ text: " av ", size: 16 }),
                      new TextRun({ children: [PageNumber.TOTAL_PAGES], size: 16 }),
                    ],
                  }),
                ],
              }),
            },
            children: [new Paragraph("{{content}}")],
          },
        ],
      }),
    ),
  );
}

const document = {
  kind: "markdown" as const,
  title: "Beslut",
  language: "sv" as const,
  content:
    "## Ärendet\n\nText **fet**.\n\n1. ett\n2. två\n\n| A | B |\n|---|--:|\n| x | 1 |\n\n<!-- pagebreak -->\n\n## Slut",
};

describe("the HTML the PDF is laid out from", () => {
  test("is semantic, escaped and shifts headings under a leading title", () => {
    const html = renderHtml(parseMarkdown(document.content), {
      title: "Beslut <2026>",
      language: "sv-SE",
      author: "Kommunen",
      lead: true,
      images: new Map(),
      footer: {
        segments: [
          { align: "left", parts: ["Kommunen"] },
          { align: "right", parts: ["Sida ", { counter: "page" }, " av ", { counter: "pages" }] },
        ],
      },
    });
    expect(html).toContain('<html lang="sv-SE">');
    expect(html).toContain("<title>Beslut &lt;2026&gt;</title>");
    expect(html).toContain('<h1 class="title">Beslut &lt;2026&gt;</h1>');
    expect(html).toContain("<h2>Ärendet</h2>");
    expect(html).toContain("<strong>fet</strong>");
    expect(html).toContain("<ol>\n<li>ett</li>");
    expect(html).toContain('<th scope="col">A</th><th scope="col" style="text-align:right">B</th>');
    expect(html).toContain('<div class="page-break" aria-hidden="true"></div>');
    expect(html).toContain(
      '<div id="page-footer" class="band"><span class="band-row"><span class="band-left">Kommunen</span><span class="band-right">Sida <span class="counter-page"></span> av <span class="counter-pages"></span></span></span></div>',
    );
    expect(html).not.toContain("page-header");
    const own = renderHtml(parseMarkdown("# Egen\n\n## Under"), {
      title: "x",
      language: "en-GB",
      lead: false,
      images: new Map(),
    });
    expect(own).toContain("<h1>Egen</h1>");
    expect(own).toContain("<h2>Under</h2>");
    expect(own).not.toContain('class="title"');
  });
  test("maps Word fonts to the faces the image ships", () => {
    expect(fontStack("Calibri")).toBe('"Calibri", "Carlito", sans-serif');
    expect(fontStack("Times New Roman")).toBe('"Times New Roman", "Liberation Serif", serif');
    expect(fontStack("Courier New")).toBe('"Courier New", "Liberation Mono", monospace');
    expect(fontStack(undefined)).toContain("Carlito");
  });
});

describe("the profile read from the Word rendering", () => {
  test("carries page, faces, header, footer, counters and the logo", async () => {
    const docx = await renderIntoTemplate(
      await letterhead(),
      { ...document, fields: { dnr: "KS 2026/7" } },
      { images: new Map(), organisationName: "Sundsvalls kommun" },
    );
    const directory = await mkdtemp(join(tmpdir(), "eneo-profile-"));
    const profile = await pdfProfile(docx, directory);
    expect(profile.page.widthMm).toBeCloseTo(210, 0);
    expect(profile.page.marginMm.top).toBeCloseTo(40, 0);
    expect(profile.page.marginMm.left).toBeCloseTo(30, 0);
    expect(profile.page.headerMm).toBeCloseTo(10, 2);
    expect(profile.page.footerMm).toBeCloseTo(10, 2);
    expect(profile.body).toMatchObject({ font: "Arial", sizePt: 10, afterPt: 6, lineHeight: "1.32" });
    expect(profile.headings[1]).toMatchObject({
      font: "Cambria",
      sizePt: 16,
      bold: true,
      color: "#1f4e79",
      beforePt: 18,
      afterPt: 6,
    });
    expect(profile.header?.logo).toMatchObject({ file: "logo.png", widthPt: 90, heightPt: 30 });
    expect(await Bun.file(join(directory, "logo.png")).exists()).toBe(true);
    expect(profile.header?.segments).toEqual([{ align: "left", parts: ["Dnr KS 2026/7"] }]);
    expect(profile.footer?.segments).toEqual([
      { align: "left", parts: ["Sundsvalls kommun"] },
      { align: "right", parts: ["Sida ", { counter: "page" }, " av ", { counter: "pages" }] },
    ]);
    expect(profile.footer?.face).toEqual({ sizePt: 8 });
    const css = profileCss(profile);
    expect(css).toMatch(/size: 210\.0\dmm 297\.0\dmm/);
    expect(css).toContain("margin: 40.00mm 20.00mm 30.00mm 30.00mm");
    expect(css).toContain(
      'font-family: "Arial", "Liberation Sans", sans-serif;\n  font-size: 10pt;\n  line-height: 1.32',
    );
    expect(css).toMatch(
      /h1 \{ font-family: "Cambria", "Caladea", serif; font-size: 16pt; color: #1f4e79; font-weight: 700; margin: 18pt 0 6pt; \}/,
    );
    expect(css).toContain("p, ul, ol, pre, table, figure, blockquote { margin: 0pt 0 6pt; }");
    // The bands span the text width, start at Word's header and footer distances, and
    // keep their own type size.
    expect(css).toContain(
      "@top-left { content: element(page-header); width: 160.00mm; vertical-align: top; padding-top: 10.00mm; }",
    );
    expect(css).toContain(
      "@bottom-left { content: element(page-footer); width: 160.00mm; vertical-align: bottom; padding-bottom: 10.00mm; }",
    );
    expect(css).toContain("#page-footer { position: running(page-footer); font-size: 8pt; }");
  });
  test("a header taller than the top margin pushes the page content down, as in Word", () => {
    const css = profileCss({
      page: {
        widthMm: 210,
        heightMm: 297,
        marginMm: { top: 20, right: 20, bottom: 20, left: 20 },
        headerMm: 10,
        footerMm: 10,
      },
      body: { sizePt: 11 },
      title: {},
      headings: [],
      header: { segments: [], logo: { file: "logo.png", widthPt: 120, heightPt: 60 } },
    });
    // 10 mm distance + 60 pt logo + gaps, so the text starts under the logo.
    expect(css).toMatch(/margin: 34\.\d\dmm 20\.00mm 20\.00mm 20\.00mm/);
  });
  test("the built-in template gives a profile with a footer and no logo", async () => {
    const docx = await renderIntoTemplate(await builtinTemplate("en"), document, {
      images: new Map(),
      organisationName: "Eneo",
    });
    const profile = await pdfProfile(docx, await mkdtemp(join(tmpdir(), "eneo-profile-")));
    expect(profile.body).toMatchObject({ font: "Calibri", sizePt: 11 });
    expect(profile.header).toEqual({ segments: [{ align: "right", parts: ["Eneo"] }] });
    expect(profile.footer?.segments).toEqual([
      { align: "left", parts: ["Beslut"] },
      { align: "right", parts: ["Page ", { counter: "page" }, " of ", { counter: "pages" }] },
    ]);
  });
});

describe.skipIf(!(await pdfAvailable()))("the PDF engine", () => {
  test("lays the document out in the template's profile as a tagged PDF", async () => {
    const { buffer, pages } = await renderDocument("pdf", document, {
      template: await letterhead(),
      organisationName: "Sundsvalls kommun",
    });
    expect(buffer.subarray(0, 5).toString()).toBe("%PDF-");
    expect(pages).toBe(2);
    await Bun.write("/tmp/eneo-letterhead.pdf", buffer);
    const facts = await inspectPdf(buffer);
    expect(facts).toMatchObject({
      lang: "sv-SE",
      title: "Beslut",
      marked: true,
      structured: true,
      pages: 2,
    });
    expect(facts.fonts.some((font) => /Liberation-?Sans/.test(font))).toBe(true);
    expect(facts.fonts.some((font) => /Caladea/.test(font))).toBe(true);
    expect(facts.xmp).toContain("pdfuaid");
    expect(facts.pageSize[0]).toBeCloseTo(595.3, 0);
    expect(facts.pageSize[1]).toBeCloseTo(841.9, 0);
    // The logo travels as an image.
    expect(buffer.toString("latin1")).toContain("/Subtype /Image");
  });
  test("without a template the built-in profile applies", async () => {
    const { buffer, pages } = await renderDocument("pdf", { ...document, language: "en" });
    expect(pages).toBe(2);
    const facts = await inspectPdf(buffer);
    expect(facts.lang).toBe("en-GB");
    expect(facts.fonts.some((font) => /Carlito/.test(font))).toBe(true);
  });
});
