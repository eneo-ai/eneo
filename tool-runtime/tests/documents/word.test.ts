import { describe, expect, test } from "bun:test";
import {
  Document,
  Footer,
  Header,
  LevelFormat,
  Packer,
  Paragraph,
  TextRun,
  type IParagraphStyleOptions,
} from "docx";
import JSZip from "jszip";
import { documentConfigSchema } from "../../src/tools/documents/config";
import { executeInspect, executeRender } from "../../src/tools/documents/execute";
import { renderDocument } from "../../src/tools/documents/engine/render";
import { fillTemplateDocx, renderIntoTemplate } from "../../src/tools/documents/engine/word/apply";
import { builtinTemplate } from "../../src/tools/documents/engine/word/builtin";
import { inspectTemplate, toReport } from "../../src/tools/documents/engine/word/inspect";
import { ListParagraph } from "../../src/tools/documents/engine/word/list-paragraph";
import { documentTools, fileInspector, fileRenderer } from "../../src/tools/documents/tool";
import { RichResult, type CallContext } from "../../src/tools/types";

const NO_IMAGES = { images: new Map() };
const DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document";

async function partOf(buffer: Buffer, name: string): Promise<string> {
  const zip = await JSZip.loadAsync(buffer);
  return (await zip.file(name)?.async("string")) ?? "";
}
const textOf = (xml: string) => xml.replace(/<[^>]+>/g, "");
async function rewrite(
  buffer: Buffer,
  edits: Record<string, (xml: string) => string>,
): Promise<Buffer> {
  const zip = await JSZip.loadAsync(buffer);
  for (const [name, edit] of Object.entries(edits))
    zip.file(name, edit(await zip.file(name)!.async("string")));
  return Buffer.from(await zip.generateAsync({ type: "nodebuffer" }));
}

/** A template made in Swedish Word: localised style ids, list styles linked to numbering. */
async function swedishTemplate(): Promise<Buffer> {
  const listStyle = (id: string, name: string, reference: string): IParagraphStyleOptions => ({
    id,
    name,
    basedOn: "Normal",
    paragraph: { numbering: { reference, level: 0 } },
  });
  const packed = Buffer.from(
    await Packer.toBuffer(
      new Document({
        numbering: {
          config: [
            {
              reference: "mall-punkter",
              levels: [{ level: 0, format: LevelFormat.BULLET, text: "–" }],
            },
            {
              reference: "mall-nummer",
              levels: [{ level: 0, format: LevelFormat.LOWER_ROMAN, text: "%1)" }],
            },
          ],
        },
        styles: {
          paragraphStyles: [
            listStyle("Punktlista", "List Bullet", "mall-punkter"),
            listStyle("Numreradlista", "List Number", "mall-nummer"),
          ],
        },
        sections: [
          {
            headers: { default: new Header({ children: [new Paragraph("Dnr {{dnr}}")] }) },
            footers: { default: new Footer({ children: [new Paragraph("{{datum}}")] }) },
            children: [
              new Paragraph({ children: [new TextRun("{{con"), new TextRun("tent}}")] }),
              new Paragraph("Efter innehållet"),
            ],
          },
        ],
      }),
    ),
  );
  const localise = (xml: string) =>
    xml.replace(/Heading(\d)/g, "Rubrik$1").replace(/"Title"/g, '"Rubrik"');
  return rewrite(packed, {
    // Only the ids are localised; Word keeps the English style names.
    "word/styles.xml": (xml) =>
      localise(xml).replace('<w:name w:val="Rubrik"/>', '<w:name w:val="Title"/>'),
    "word/document.xml": localise,
  });
}

const PLACEHOLDER_RUN =
  '<w:r><w:rPr><w:rStyle w:val="PlaceholderText"/></w:rPr><w:t xml:space="preserve">';
const textControl = (tag: string, alias: string, hint: string) =>
  `<w:sdt><w:sdtPr><w:alias w:val="${alias}"/><w:tag w:val="${tag}"/><w:id w:val="1"/><w:showingPlcHdr/><w:text/></w:sdtPr><w:sdtContent>${PLACEHOLDER_RUN}${hint}</w:t></w:r></w:sdtContent></w:sdt>`;
const richControl = (tag: string, alias: string, hint: string) =>
  `<w:sdt><w:sdtPr><w:alias w:val="${alias}"/><w:tag w:val="${tag}"/><w:id w:val="2"/><w:showingPlcHdr/></w:sdtPr><w:sdtContent><w:p>${PLACEHOLDER_RUN}${hint}</w:t></w:r></w:p></w:sdtContent></w:sdt>`;
const heading = (text: string) =>
  `<w:p><w:pPr><w:pStyle w:val="Heading1"/></w:pPr><w:r><w:t>${text}</w:t></w:r></w:p>`;

/** A template with content controls, in the shape Word (and Flows' standard templates) write. */
async function controlTemplate(body: string): Promise<Buffer> {
  const packed = Buffer.from(
    await Packer.toBuffer(
      new Document({
        sections: [
          {
            headers: {
              default: new Header({ children: [new Paragraph("Sundsvalls kommun")] }),
            },
            children: [new Paragraph("BODY")],
          },
        ],
      }),
    ),
  );
  return rewrite(packed, {
    "word/document.xml": (xml) =>
      xml.replace(/<w:p><w:r><w:t[^>]*>BODY<\/w:t><\/w:r><\/w:p>/, body),
  });
}
const REPORT_BODY =
  `<w:p><w:pPr><w:pStyle w:val="Title"/></w:pPr>${textControl("titel", "Rapportens titel", "Rapportens titel")}</w:p>` +
  `<w:p><w:r><w:t xml:space="preserve">Datum: </w:t></w:r>${textControl("datum", "Datum", "ÅÅÅÅ-MM-DD")}</w:p>` +
  heading("Sammanfattning") +
  richControl("sammanfattning", "Sammanfattning", "Två till fyra stycken.") +
  heading("Bakgrund") +
  richControl("bakgrund", "Bakgrund", "Beskriv bakgrund och syfte.");
const DOCUMENT_BODY =
  `<w:p><w:pPr><w:pStyle w:val="Title"/></w:pPr>${textControl("titel", "Titel", "Dokumentets titel")}</w:p>` +
  richControl("dokument", "Dokument", "Hela dokumentet.");

describe("inspection", () => {
  test("reads content controls with their labels, guidance and surrounding heading", async () => {
    const inspection = await inspectTemplate(await controlTemplate(REPORT_BODY));
    expect(inspection.syntax).toBe("controls");
    expect(inspection.placeholders.map((p) => [p.name, p.kind, p.headingLevel])).toEqual([
      ["titel", "text", 0],
      ["datum", "text", 0],
      ["sammanfattning", "rich", 1],
      ["bakgrund", "rich", 1],
    ]);
    expect(inspection.placeholders[0]).toMatchObject({
      label: "Rapportens titel",
      hint: "Rapportens titel",
      location: "body",
      supported: true,
      block: false,
    });
    expect(inspection.placeholders[2]).toMatchObject({
      hint: "Två till fyra stycken.",
      block: true,
    });
    expect(inspection.contentPlaceholder).toBeUndefined();
    expect(inspection.checks.content_placeholder!.ok).toBe(false);
    expect(inspection.checks.heading_styles!.ok).toBe(true);
    expect(inspection.styles.heading[1]).toBe("Heading1");
    expect(inspection.styles.title).toBe("Title");
    const report = toReport(inspection);
    expect(report.placeholders[0]).toEqual({
      name: "titel",
      syntax: "control",
      kind: "text",
      label: "Rapportens titel",
      hint: "Rapportens titel",
      location: "body",
      supported: true,
    });
    expect(Object.keys(report)).not.toContain("styles");
  });
  test("resolves Swedish style ids by name and finds the template's list numbering", async () => {
    const inspection = await inspectTemplate(await swedishTemplate());
    expect(inspection.syntax).toBe("braces");
    expect(inspection.styles.heading.slice(1, 4)).toEqual(["Rubrik1", "Rubrik2", "Rubrik3"]);
    expect(inspection.styles.listBullet[0]).toBe("Punktlista");
    expect(inspection.styles.listNumber[0]).toBe("Numreradlista");
    expect(inspection.listNumbering.bullet).toBeNumber();
    expect(inspection.listNumbering.number).toBeNumber();
    expect(inspection.contentPlaceholder).toMatchObject({ name: "content", syntax: "braces" });
    expect(inspection.placeholders.map((p) => [p.name, p.location])).toEqual([
      ["content", "body"],
      ["dnr", "header"],
      ["datum", "footer"],
    ]);
    expect(inspection.checks.list_styles!.ok).toBe(true);
    expect(inspection.page.width).toBeCloseTo(451.3, 0);
  });
  test("marks controls it cannot fill and reports why", async () => {
    const nested = richControl("yttre", "Yttre", "x").replace(
      "<w:p>" + PLACEHOLDER_RUN,
      `<w:p>${textControl("inre", "Inre", "y")}${PLACEHOLDER_RUN}`,
    );
    const date = textControl("när", "När", "z").replace("<w:text/>", "<w:date/>");
    const inspection = await inspectTemplate(await controlTemplate(nested + `<w:p>${date}</w:p>`));
    expect(inspection.placeholders.map((p) => [p.name, p.supported, p.reason])).toEqual([
      ["yttre", true, undefined],
      ["inre", false, "nested inside another control"],
      ["när", false, "date controls are not filled"],
    ]);
  });
});

describe("rendering into templates", () => {
  const document = {
    kind: "markdown" as const,
    title: "Rapport om trygghet",
    language: "sv" as const,
    content: "## Läge\n\nText.\n\n1. ett\n2. två\n\nMellan.\n\n1. tre\n\n- punkt\n  - under",
  };
  test("writes the content in the template's own styles and lists", async () => {
    const buffer = await renderIntoTemplate(await swedishTemplate(), document, {
      ...NO_IMAGES,
      organisationName: "Kommunen",
    });
    const xml = await partOf(buffer, "word/document.xml");
    // The title leads the content in the title style; headings take the localised ids.
    expect(xml).toMatch(/<w:pStyle w:val="Rubrik"\/>[^]*?Rapport om trygghet/);
    expect(xml).toMatch(/<w:pStyle w:val="Rubrik2"\/>[^]*?Läge/);
    expect(xml).not.toContain("Heading");
    expect(xml).toContain('<w:pStyle w:val="Punktlista"/>');
    expect(xml).toContain('<w:pStyle w:val="Numreradlista"/>');
    expect(xml).not.toContain("{{");
    expect(xml.indexOf("Rapport om trygghet")).toBeLessThan(xml.indexOf("Efter innehållet"));
    // Each numbered list is its own instance that restarts at 1, on the template's numbering.
    const numbered = [
      ...xml.matchAll(
        /<w:pStyle w:val="Numreradlista"\/><w:numPr><w:ilvl w:val="0"\/><w:numId w:val="(\d+)"\/>/g,
      ),
    ].map((m) => m[1]);
    expect(numbered).toHaveLength(3);
    expect(new Set(numbered).size).toBe(2);
    const numbering = await partOf(buffer, "word/numbering.xml");
    for (const id of new Set(numbered))
      expect(numbering).toMatch(
        new RegExp(
          `<w:num w:numId="${id}"><w:abstractNumId w:val="\\d+"/><w:lvlOverride w:ilvl="0"><w:startOverride w:val="1"/>`,
        ),
      );
    expect(numbering).toContain("lowerRoman");
    expect(numbering).not.toContain('w:val="decimal"');
    // Bullets nest by level on one shared instance.
    expect(xml).toMatch(/<w:pStyle w:val="Punktlista"\/><w:numPr><w:ilvl w:val="1"\/>/);
    // Header and footer placeholders the document knows are filled on their own.
    expect(await partOf(buffer, "word/footer1.xml")).toContain(
      new Date().toISOString().slice(0, 10),
    );
    expect(await partOf(buffer, "word/header1.xml")).toContain("{{dnr}}");
    const core = await partOf(buffer, "docProps/core.xml");
    expect(core).toContain("<dc:title>Rapport om trygghet</dc:title>");
    expect(core).toContain("<dc:creator>Kommunen</dc:creator>");
  });
  test("fields cover the rest of the placeholders, and every one needs a value", async () => {
    const template = await swedishTemplate();
    const buffer = await renderIntoTemplate(
      template,
      { ...document, fields: { dnr: "KS 2026/12" } },
      NO_IMAGES,
    );
    expect(textOf(await partOf(buffer, "word/header1.xml"))).toBe("Dnr KS 2026/12");
    await expect(
      renderIntoTemplate(template, { ...document, fields: { annat: "x" } }, NO_IMAGES),
    ).rejects.toMatchObject({ code: "TEMPLATE_VALUES_MISSING" });
  });
  test("fills a content control and the title control, without a second title", async () => {
    const buffer = await renderIntoTemplate(
      await controlTemplate(DOCUMENT_BODY),
      { ...document, content: "# Egen rubrik\n\nText." },
      NO_IMAGES,
    );
    const xml = await partOf(buffer, "word/document.xml");
    expect(xml).not.toContain("showingPlcHdr");
    expect(xml).not.toContain("{{");
    expect(xml).toMatch(/<w:tag w:val="titel"\/>[^]*?<w:sdtContent><w:r>[^]*?Rapport om trygghet/);
    expect(xml).toMatch(
      /<w:tag w:val="dokument"\/>[^]*?<w:sdtContent><w:p><w:pPr><w:pStyle w:val="Heading1"\/>/,
    );
    expect(xml.match(/Rapport om trygghet/g)).toHaveLength(1);
    expect(xml).not.toContain(
      '<w:pStyle w:val="Title"/></w:pPr><w:r><w:t xml:space="preserve">Rapport',
    );
  });
});

describe("filling templates", () => {
  test("rich controls take Markdown under their heading, empty values remove a control", async () => {
    const template = await controlTemplate(REPORT_BODY);
    const { buffer, placeholders } = await fillTemplateDocx(template, {
      titel: "Trygghet 2026",
      datum: "2026-10-09",
      sammanfattning: "Första stycket.\n\n## Delmål\n\n- a\n- b",
      bakgrund: "",
    });
    expect(placeholders).toEqual(["titel", "datum", "sammanfattning", "bakgrund"]);
    const xml = await partOf(buffer, "word/document.xml");
    expect(xml).not.toContain("{{");
    expect(xml).not.toContain("PlaceholderText");
    expect(textOf(xml)).toContain("Datum: 2026-10-09");
    expect(xml).toMatch(/<w:tag w:val="titel"\/>[^]*?Trygghet 2026/);
    // A heading in the control's Markdown sits one level under the heading above the control.
    expect(xml).toMatch(/<w:pStyle w:val="Heading3"\/>[^]*?Delmål/);
    expect(xml).toMatch(/<w:numPr><w:ilvl w:val="0"\/><w:numId w:val="\d+"\/><\/w:numPr>[^]*?>a</);
    expect(xml).not.toContain('w:val="bakgrund"');
    expect(textOf(xml)).toContain("Bakgrund");
    expect(await partOf(buffer, "word/header1.xml")).toContain("Sundsvalls kommun");

    const missing = fillTemplateDocx(template, { titel: "x" });
    await expect(missing).rejects.toMatchObject({ code: "TEMPLATE_VALUES_MISSING" });
    await expect(missing).rejects.toThrow(
      'sammanfattning "Sammanfattning" (a document in Markdown): Två till fyra stycken.',
    );
    await expect(missing).rejects.toThrow(
      "No value was given for: datum, sammanfattning, bakgrund.",
    );
  });
  test("a template with nothing to fill is refused with advice", async () => {
    await expect(
      renderDocument(
        "docx",
        { kind: "fill", template: { index: 0 }, values: {} },
        { template: await controlTemplate("<w:p><w:r><w:t>Bara text</w:t></w:r></w:p>") },
      ),
    ).rejects.toThrow("no content controls or {{placeholders}}");
  });
});

describe("the built-in template", () => {
  test("carries styles, a content control and placeholders, and renders without one given", async () => {
    const template = await builtinTemplate("sv");
    const inspection = await inspectTemplate(template);
    expect(inspection.syntax).toBe("mixed");
    expect(inspection.contentPlaceholder).toMatchObject({ name: "content", kind: "rich" });
    expect(inspection.styles.listBullet[0]).toBe("ListBullet");
    expect(inspection.styles.quote).toBe("Quote");
    expect(inspection.language).toBe("sv-SE");
    expect(inspection.listNumbering.bullet).toBeNumber();
    for (const name of [
      "content_placeholder",
      "heading_styles",
      "title_style",
      "list_styles",
      "language",
    ])
      expect(inspection.checks[name]!.ok).toBe(true);
    expect(inspection.placeholders.map((p) => [p.name, p.location])).toEqual([
      ["content", "body"],
      ["organisation", "header"],
      ["title", "footer"],
    ]);
    const { buffer } = await renderDocument(
      "docx",
      {
        kind: "markdown",
        title: "Plan",
        language: "sv",
        content: "## Steg\n\n> Citat\n\n- a\n\n1. b",
      },
      { organisationName: "Kommunen" },
    );
    const xml = await partOf(buffer, "word/document.xml");
    expect(xml).not.toContain("{{");
    expect(xml).toMatch(/<w:pStyle w:val="Title"\/>[^]*?Plan/);
    expect(xml).toContain('<w:pStyle w:val="Quote"/>');
    expect(xml).toContain('<w:pStyle w:val="ListBullet"/>');
    expect(xml).toContain('<w:pStyle w:val="ListNumber"/>');
    expect(await partOf(buffer, "word/header1.xml")).toContain("Kommunen");
    expect(await partOf(buffer, "word/footer1.xml")).toContain("Plan");
    expect(await partOf(buffer, "docProps/core.xml")).toContain("<dc:language>sv-SE</dc:language>");
    expect(await partOf(await builtinTemplate("en"), "word/footer1.xml")).toContain("Page ");
  });
});

describe("list paragraphs", () => {
  test("write the numbering reference into the paragraph properties", async () => {
    const buffer = Buffer.from(
      await Packer.toBuffer(
        new Document({
          sections: [
            {
              children: [
                new ListParagraph(
                  { style: "Punkt", children: [new TextRun("a")] },
                  { numId: 7, level: 1 },
                ),
                new ListParagraph({ children: [new TextRun("b")] }, { numId: 8, level: 0 }),
              ],
            },
          ],
        }),
      ),
    );
    const xml = await partOf(buffer, "word/document.xml");
    expect(xml).toContain(
      '<w:pPr><w:pStyle w:val="Punkt"/><w:numPr><w:ilvl w:val="1"/><w:numId w:val="7"/></w:numPr></w:pPr>',
    );
    expect(xml).toContain(
      '<w:pPr><w:numPr><w:ilvl w:val="0"/><w:numId w:val="8"/></w:numPr></w:pPr>',
    );
  });
});

describe("the fill_template tool", () => {
  const config = documentConfigSchema.parse({});
  const render = fileRenderer(executeRender);
  const inspect = fileInspector(executeInspect);
  const ORIGIN = "http://backend:8000";
  const sources = new Map<string, Buffer>();
  const access = {
    allowedFileOrigins: [],
    maxBytes: 20 * 1024 * 1024,
    timeoutMs: 5_000,
    download: (async (raw: string) => {
      const bytes = sources.get(new URL(raw).searchParams.get("token")!);
      if (!bytes) throw new Error("response:403");
      return { bytes, contentType: DOCX_MIME, name: "source" };
    }) as never,
  };
  const url = (token: string) =>
    `${ORIGIN}/api/v1/files/11111111-1111-4111-8111-111111111111/original/download/?token=${token}`;
  const context: CallContext = { tenantId: "", userId: "", fileOrigin: ORIGIN };
  const tools = Object.fromEntries(
    documentTools(config, render, access, inspect).map((t) => [t.name, t]),
  );
  test("lists a Word template's fields on request, then fills them", async () => {
    sources.set("rapport", await controlTemplate(REPORT_BODY));
    const template = { url: url("rapport"), filename: "rapport.docx" };
    const listed = (await tools.fill_template!.execute(
      { template, inspect: true },
      context,
    )) as Record<string, unknown>;
    expect(listed).toMatchObject({ template: "rapport.docx", syntax: "controls" });
    expect((listed.placeholders as { name: string }[]).map((p) => p.name)).toEqual([
      "titel",
      "datum",
      "sammanfattning",
      "bakgrund",
    ]);
    expect(String(listed.next)).toContain("value for every supported field");
    await expect(tools.fill_template!.execute({ template }, context)).rejects.toMatchObject({
      code: "VALUES_REQUIRED",
    });
    const filled = (await tools.fill_template!.execute(
      {
        template,
        values: { titel: "T", datum: "D", sammanfattning: "S", bakgrund: "B" },
      },
      context,
    )) as RichResult;
    expect(filled.structured).toMatchObject({ filename: "rapport.docx", format: "docx" });
    expect(
      textOf(await partOf(Buffer.from(filled.files[0]!.blob, "base64"), "word/document.xml")),
    ).toContain("Datum: D");
  });
  test("lists a text template's placeholders without a child", async () => {
    sources.set("brev", Buffer.from("Hej {{ namn }}, {{namn}} och {{datum}}"));
    const listed = (await tools.fill_template!.execute(
      { template: { url: url("brev"), filename: "brev.md" }, inspect: true },
      context,
    )) as Record<string, unknown>;
    expect((listed.placeholders as { name: string }[]).map((p) => p.name)).toEqual([
      "namn",
      "datum",
    ]);
  });
});
