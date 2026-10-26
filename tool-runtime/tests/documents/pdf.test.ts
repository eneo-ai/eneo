import { describe, expect, test } from "bun:test";
import JSZip from "jszip";
import { Document, Footer, Header, ImageRun, Packer, Paragraph, TextRun, PageNumber } from "docx";
import { renderHtml } from "../../src/tools/documents/engine/html";
import { fontStack, pdfProfile, profileCss } from "../../src/tools/documents/engine/pdf-profile";
import { PDF_PYTHON, pdfAvailable, preparePdf } from "../../src/tools/documents/engine/pdf";
import { renderDocument } from "../../src/tools/documents/engine/render";
import { renderIntoTemplate } from "../../src/tools/documents/engine/word/apply";
import { builtinTemplate } from "../../src/tools/documents/engine/word/builtin";
import { parseMarkdown } from "../../src/tools/documents/markdown/parse";
import { inspectPdf } from "./pdf-inspect";
import { mkdtemp, readdir, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";

const PDF = await pdfAvailable();

// A 1x1 PNG, enough for a logo.
const PNG = Buffer.from(
  "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg==",
  "base64",
);

/** A municipal letterhead: Arial body, blue Cambria headings, a logo and page numbers. */
async function letterhead(bodyPicture = false): Promise<Buffer> {
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
            children: [
              ...(bodyPicture
                ? [
                    new Paragraph({
                      children: [
                        new ImageRun({
                          type: "png",
                          data: PNG,
                          transformation: { width: 20, height: 20 },
                        }),
                      ],
                    }),
                  ]
                : []),
              new Paragraph({ children: [new TextRun("Dnr {{dnr}}")] }),
              new Paragraph("{{content}}"),
              new Paragraph({
                children: [new TextRun({ text: "Beslutet kan överklagas.", italics: true })],
              }),
            ],
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

describe("PDF template resource boundaries", () => {
  test.skipIf(!PDF)("renders a legitimate template with both raster paths as a tagged PDF", async () => {
    const { buffer, pages } = await renderDocument(
      "pdf",
      { ...document, content: "A short document.", fields: { dnr: "1" } },
      { template: await letterhead(true) },
    );
    expect(pages).toBe(1);
    const facts = await inspectPdf(buffer);
    expect(facts).toMatchObject({ title: document.title, marked: true, structured: true });
    expect(buffer.toString("latin1")).toContain("/Subtype /Image");
  });

  test("custom face names remain CSS strings, including control characters and prototype names", () => {
    expect(fontStack("noto-sans-2")).toBe('"noto-sans-2", sans-serif');
    expect(fontStack("Åke's font")).toBe('\"Åke\'s font\", sans-serif');
    expect(fontStack('Face"\\\n\r\f\0')).toBe('"Face\\22 \\5c \\a \\d \\c \\fffd ", sans-serif');
    expect(fontStack("constructor")).toBe('"constructor", sans-serif');
    expect(fontStack("__proto__")).toBe('"__proto__", sans-serif');
  });

  test.skipIf(!PDF)(
    "every face stays data in the PDF sidecar's CSS parser",
    () => {
      const font = 'Face";color:red;} html{font-family:"Other\\Face';
      const face = { font };
      const css = profileCss({
        page: {
          widthMm: 210,
          heightMm: 297,
          marginMm: { top: 20, right: 20, bottom: 20, left: 20 },
          headerMm: 10,
          footerMm: 10,
        },
        body: face,
        title: face,
        headings: [{}, face, face, face],
        header: { face, segments: [{ align: "left", parts: ["Header"] }] },
        footer: { face, segments: [{ align: "left", parts: ["Footer"] }] },
      });
      const parsed = Bun.spawnSync(
        [
          PDF_PYTHON,
          "-I",
          "-c",
          `
import json, sys, tinycss2
rules = tinycss2.parse_stylesheet(sys.stdin.read(), skip_whitespace=True, skip_comments=True)
faces = []
for rule in rules:
    if rule.type == 'qualified-rule':
        for declaration in tinycss2.parse_declaration_list(rule.content, skip_whitespace=True, skip_comments=True):
            if declaration.type == 'declaration' and declaration.lower_name == 'font-family':
                faces.append(next(token.value for token in declaration.value if token.type == 'string'))
print(json.dumps({'faces': faces, 'selectors': [tinycss2.serialize(rule.prelude).strip() for rule in rules if rule.type == 'qualified-rule']}))
`,
        ],
        { stdin: Buffer.from(css) },
      );
      expect(parsed.exitCode).toBe(0);
      const result = JSON.parse(parsed.stdout.toString()) as {
        faces: string[];
        selectors: string[];
      };
      // Body, title, all three heading faces and both running bands use one serializer.
      expect(result.faces.filter((name) => name === font)).toHaveLength(7);
      expect(result.selectors.filter((selector) => selector === "html")).toHaveLength(1);
      expect(result.selectors).not.toContain("Other");
    },
  );

  test("theme colors admit only RGB values for both Word theme color forms", async () => {
    for (const [color, expected] of [
      ["1F4E79", "#1f4e79"],
      ["123456;color:red", undefined],
    ] as const) {
      for (const kind of ["srgbClr", "sysClr"] as const) {
        const zip = await JSZip.loadAsync(await letterhead());
        const styles = await zip.file("word/styles.xml")!.async("string");
        zip.file(
          "word/styles.xml",
          styles.replace('<w:color w:val="1F4E79"/>', '<w:color w:themeColor="accent1"/>'),
        );
        zip.file(
          "word/theme/theme1.xml",
          `<a:theme xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"><a:themeElements><a:clrScheme><a:accent1><a:${kind} ${kind === "sysClr" ? 'val="windowText" lastClr' : "val"}="${color}"/></a:accent1></a:clrScheme></a:themeElements></a:theme>`,
        );
        const directory = await mkdtemp(join(tmpdir(), "eneo-profile-colors-"));
        try {
          const profile = await pdfProfile(
            Buffer.from(await zip.generateAsync({ type: "nodebuffer" })),
            directory,
          );
          expect(profile.headings[1]?.color).toBe(expected);
          expect(profileCss(profile)).not.toContain("123456;color:red");
        } finally {
          await rm(directory, { recursive: true, force: true });
        }
      }
    }
  });

  test("rejects disguised and oversized resources in both logo and body picture paths", async () => {
    const oversized = Buffer.from(PNG);
    oversized.writeUInt32BE(12001, 16);
    for (const body of [false, true]) {
      for (const bytes of [Buffer.from("wOF2: invalid image"), oversized]) {
        const zip = await JSZip.loadAsync(await letterhead(body));
        for (const name of Object.keys(zip.files).filter(
          (name) => name.startsWith("word/media/") && name.endsWith(".png"),
        ))
          zip.file(name, bytes);
        const template = Buffer.from(await zip.generateAsync({ type: "nodebuffer" }));
        const directory = await mkdtemp(join(tmpdir(), "eneo-profile-images-"));
        try {
          if (!body) {
            await expect(pdfProfile(template, directory)).rejects.toThrow("valid PNG or JPEG");
          } else {
            // Keep the header valid so this control reaches body picture extraction.
            const header = await zip.file("word/header1.xml")!.async("string");
            zip.file("word/header1.xml", header.replace(/<w:drawing[\s\S]*?<\/w:drawing>/g, ""));
            await expect(
              preparePdf(
                { ...document, fields: { dnr: "1" } },
                {
                  template: Buffer.from(await zip.generateAsync({ type: "nodebuffer" })),
                  images: new Map(),
                },
              ),
            ).rejects.toThrow("valid PNG or JPEG");
          }
          expect(await readdir(directory)).toEqual([]);
        } finally {
          await rm(directory, { recursive: true, force: true });
        }
      }
    }
  });

  test("ignores external logos and names recognized bitmaps from their bytes", async () => {
    for (const external of [false, true]) {
      const zip = await JSZip.loadAsync(await letterhead());
      const rels = await zip.file("word/_rels/header1.xml.rels")!.async("string");
      const name = Object.keys(zip.files).find(
        (name) => name.startsWith("word/media/") && name.endsWith(".png"),
      )!;
      zip.file(name.replace(/\.png$/, ".jpg"), PNG);
      zip.remove(name);
      zip.file(
        "word/_rels/header1.xml.rels",
        rels
          .replace(/\.png/g, ".jpg")
          .replace(
            /(<Relationship\s[^>]*Type="[^"]*\/image")/,
            `$1${external ? ' TargetMode="External"' : ""}`,
          ),
      );
      const directory = await mkdtemp(join(tmpdir(), "eneo-profile-logo-"));
      try {
        const profile = await pdfProfile(
          Buffer.from(await zip.generateAsync({ type: "nodebuffer" })),
          directory,
        );
        expect(profile.header?.logo?.file).toBe(external ? undefined : "logo.png");
        expect(await readdir(directory)).toEqual(external ? [] : ["logo.png"]);
      } finally {
        await rm(directory, { recursive: true, force: true });
      }
    }
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

describe("the template body in the PDF", () => {
  test("keeps the template's own text around the content, filled, and the title where it sits", async () => {
    const { html } = await preparePdf(
      { ...document, fields: { dnr: "KS 2026/7" } },
      { template: await letterhead(), images: new Map(), organisationName: "Sundsvalls kommun" },
    );
    const main = html.slice(html.indexOf("<main"), html.indexOf("</main>"));
    expect(main).toMatch(
      /<p>Dnr KS 2026\/7<\/p>\n<h1 class="title">Beslut<\/h1>\n<h2>Ärendet<\/h2>[^]*<h2>Slut<\/h2>\n<p><em>Beslutet kan överklagas.<\/em><\/p>/,
    );
    expect(main.match(/<h1 class="title">/g)).toHaveLength(1);
    // The running title in the header shows the title, not the marker.
    expect(html).not.toMatch(/eneo-(title|content)-/);
  });
  test("a content starting with its own heading gets no second title", async () => {
    const { html } = await preparePdf(
      { ...document, content: "# Egen titel\n\nText.", fields: { dnr: "KS 2026/8" } },
      { template: await letterhead(), images: new Map() },
    );
    expect(html).not.toContain('class="title"');
    expect(html).toContain("<p>Dnr KS 2026/8</p>\n<h1>Egen titel</h1>");
  });
});

describe.skipIf(!PDF)("the PDF engine", () => {
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
