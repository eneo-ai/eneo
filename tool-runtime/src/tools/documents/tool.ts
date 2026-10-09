import { mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { z } from "zod";
import { ToolError } from "../../errors";
import {
  documentReference,
  earlierDocumentReference,
  earlierMarkdownReference,
  earlierWorkbookReference,
  fetchReference,
  fileHandle,
  fileReference,
  imageReference,
  templateReference,
  type ReferenceAccess,
} from "../files/reference";
import { RichResult, type ToolDefinition } from "../types";
import type { DocumentConfig, ExportFormat } from "./config";
import { applyEdits, documentEdit, MAX_EDITS } from "./edits";
import { textPlaceholders } from "./engine/fill";
import { MIME_BY_FORMAT, safeFilename } from "./filename";
import type {
  BuiltinTemplateJob,
  DocumentRequest,
  InspectJob,
  InspectResult,
  RenderJob,
  RenderResult,
  SheetRequest,
  TemplateReport,
} from "./ports";

type RenderRequest = Omit<RenderJob, "kind" | "outputPath"> & {
  /** Downloaded sheet sources, referenced by `SheetSource.index`. */
  sources?: Buffer[];
};
/** Renders a document and returns its bytes. */
export type Renderer = (request: RenderRequest) => Promise<{ buffer: Buffer; pages?: number }>;

/**
 * Runs a render job (normally in a sandbox child) against an output file in a directory the
 * parent owns, so the document never has to fit through the child's bounded stdout.
 */
export function fileRenderer(run: (job: RenderJob) => Promise<RenderResult>): Renderer {
  return async ({ sources = [], ...request }) => {
    const directory = await mkdtemp(join(tmpdir(), "eneo-tool-runtime-render-"));
    try {
      const outputPath = join(directory, "output");
      for (const [index, bytes] of sources.entries())
        await writeFile(join(directory, `source-${index}`), bytes, {
          mode: 0o600,
        });
      const document: DocumentRequest =
        request.document.kind !== "sheets"
          ? request.document.template
            ? {
                ...request.document,
                template: {
                  ...request.document.template,
                  path: join(directory, `source-${request.document.template.index}`),
                },
              }
            : request.document
          : {
              ...request.document,
              sheets: request.document.sheets.map((sheet) =>
                sheet.source
                  ? {
                      ...sheet,
                      source: {
                        ...sheet.source,
                        path: join(directory, `source-${sheet.source.index}`),
                      },
                    }
                  : sheet,
              ),
            };
      if (document.kind === "markdown" && document.images) {
        document.images = document.images.map((image) => ({
          ...image,
          path: join(directory, `source-${image.index}`),
        }));
      }
      const result = await run({
        kind: "render_document",
        ...request,
        document,
        outputPath,
      });
      return { buffer: await readFile(outputPath), pages: result.pages };
    } finally {
      await rm(directory, { recursive: true, force: true });
    }
  };
}

/** Reads a Word template's placeholders (normally in a sandbox child). */
export type TemplateInspector = (template: Buffer) => Promise<TemplateReport>;

/** Runs an inspect job against a template file in a directory the parent owns. */
export function fileInspector(run: (job: InspectJob) => Promise<InspectResult>): TemplateInspector {
  return async (template) => {
    const directory = await mkdtemp(join(tmpdir(), "eneo-tool-runtime-inspect-"));
    try {
      const templatePath = join(directory, "template");
      await writeFile(templatePath, template, { mode: 0o600 });
      return (await run({ kind: "inspect_template", templatePath })).inspection;
    } finally {
      await rm(directory, { recursive: true, force: true });
    }
  };
}

/** Builds Eneo's built-in template (in a sandbox child) and returns its bytes. */
export function builtinTemplateProvider(
  run: (job: BuiltinTemplateJob) => Promise<RenderResult>,
): (language: "sv" | "en") => Promise<Buffer> {
  return async (language) => {
    const directory = await mkdtemp(join(tmpdir(), "eneo-tool-runtime-template-"));
    try {
      const outputPath = join(directory, "output");
      await run({ kind: "builtin_template", language, outputPath });
      return await readFile(outputPath);
    } finally {
      await rm(directory, { recursive: true, force: true });
    }
  };
}

const filename = z
  .string()
  .max(100)
  .optional()
  .describe(
    "File name without extension, e.g. 'Tjänsteskrivelse trygghet'. Defaults to the title.",
  );
const cell = z.union([z.string().max(2000), z.number(), z.boolean(), z.null()]);
/** Values for a template's placeholders by name: text, or Markdown for a rich content control. */
const placeholderValues = (maxChars: number) =>
  z
    .record(z.string().min(1).max(200), z.string().max(maxChars))
    .refine((values) => Object.keys(values).length <= 200, {
      message: "At most 200 values",
    });
/** The name an earlier file was delivered under, without its extension. */
const stem = (filename: string) => filename.replace(/\.[^.]+$/, "");

/** An image a document shows, with the handle of the Eneo file it is. */
type PlacedImage = { id?: string; caption?: string; handle: string };

/**
 * A Markdown document names its images by their file handle, on a line of their own:
 * ![alt](eneo-file:… "caption"). Eneo shows the file there to whoever may read it, so the
 * document carries no bytes and no credentials. Each declared image:ID line becomes such a
 * line, set off as a paragraph of its own; the ones the content already has stay as they are.
 */
function placeImages(content: string, images: PlacedImage[]): string {
  const invalid = (message: string) => new ToolError("INVALID_IMAGES", message);
  const marker =
    /^([ \t]*(?:>[ \t]*)*)!\[([^\]\n]*)\]\(image:([A-Za-z][A-Za-z0-9_-]{0,63})\)[ \t]*$/gm;
  // Every missing declaration is named at once, so one corrected call is enough.
  const undeclared = [...new Set([...content.matchAll(marker)].map((match) => match[3]!))].filter(
    (id) => !images.some((image) => image.id === id),
  );
  if (undeclared.length)
    throw invalid(
      `${undeclared.length > 1 ? "Images" : "Image"} ${undeclared.join(", ")} ${undeclared.length > 1 ? "are" : "is"} placed in the content but not declared in images. Call again with the same content and an images entry for each: that id, with the url and filename of the PNG or JPEG it shows.`,
    );
  const placed = new Set<PlacedImage>();
  const text = content.replace(
    marker,
    (line: string, indent: string, alt: string, id: string, offset: number) => {
      const image = images.find((candidate) => candidate.id === id)!;
      placed.add(image);
      const caption = image.caption?.replace(/\s+/g, " ").replace(/["\\]/g, "\\$&");
      const placedLine = `${indent}![${alt}](${image.handle}${caption ? ` "${caption}"` : ""})`;
      if (indent) return placedLine;
      const before = content.slice(0, offset);
      const after = content.slice(offset + line.length);
      return (
        (before && !/(^|\n)[ \t]*\n$/.test(before) ? "\n" : "") +
        placedLine +
        (after && !/^\n[ \t]*(\n|$)/.test(after) ? "\n" : "")
      );
    },
  );
  if (/!\[[^\]]*\]\(image:/.test(text))
    throw invalid("Put each ![alt text](image:ID) on a line of its own.");
  const missing = images.find(
    (image) => image.id && !placed.has(image) && !text.includes(`(${image.handle}`),
  );
  if (missing)
    throw invalid(
      `Image ${missing.id} is declared but not placed: put ![alt text](image:ID) on a line of its own where it belongs.`,
    );
  return text;
}

/** The fields of a text template, in the shape a Word inspection reports. */
function textReport(template: Buffer): TemplateReport {
  const names = textPlaceholders(template);
  return {
    syntax: names.length ? "braces" : "none",
    placeholders: names.map((name) => ({
      name,
      syntax: "braces",
      kind: "text",
      location: "body",
      supported: true,
    })),
    checks: {},
  };
}

const isRaster = (bytes: Buffer) =>
  (bytes.length > 8 && bytes.readUInt32BE(0) === 0x89504e47) ||
  (bytes.length > 3 && bytes[0] === 0xff && bytes[1] === 0xd8);

/** The file travels back as an MCP embedded resource; Eneo saves it in the conversation. */
async function produce(
  render: Renderer,
  config: DocumentConfig,
  format: ExportFormat,
  name: string,
  document: DocumentRequest,
  sources: Buffer[] = [],
  replaces?: string,
): Promise<RichResult> {
  const { buffer, pages } = await render({
    format,
    document,
    sources,
    maxBytes: config.max_export_bytes,
    organisationName: config.organisation_name,
  });
  return deliver(format, name, buffer, pages, replaces);
}

/** A Markdown document is read in Eneo, beside the conversation; other files are downloads. */
function deliver(
  format: ExportFormat,
  name: string,
  buffer: Buffer,
  pages?: number,
  replaces?: string,
): RichResult {
  const shown =
    format === "md"
      ? "The document is shown to the user beside the conversation"
      : "The file is attached to this answer for the user to download";
  // Named exactly: Eneo turns a mention of the filename into a link to the file.
  return new RichResult(
    {
      filename: name,
      format,
      bytes: buffer.length,
      ...(pages !== undefined ? { pages } : {}),
      ...(replaces ? { replaces } : {}),
      delivered: replaces
        ? `${shown} and replaces ${replaces}. Say so, mention it by its exact filename; do not paste its content or invent a link.`
        : `${shown}. Mention it by its exact filename; do not paste its content or invent a link.`,
    },
    [
      {
        uri: `eneo-tool-runtime://documents/${crypto.randomUUID()}/${encodeURIComponent(name)}`,
        mimeType: MIME_BY_FORMAT[format],
        blob: buffer.toString("base64"),
      },
    ],
  );
}

export function documentTools(
  config: DocumentConfig,
  render: Renderer,
  access: ReferenceAccess,
  inspect?: TemplateInspector,
): ToolDefinition[] {
  const input = z.object({
    title: z
      .string()
      .min(1)
      .max(200)
      .describe(
        "Document title; shown as the heading unless the content starts with a level-1 heading.",
      ),
    // Before the content, so a client showing the document while it is written knows
    // what it is going to be.
    format: z
      .enum(["md", "docx", "pdf"])
      .optional()
      .describe(
        "Output format. md: a Markdown document the user reads and revises in Eneo (plans, summaries, notes, drafts). docx: a Word file that leaves Eneo. pdf: when asked for. Defaults to md; with a template to docx; when revising, to the earlier document's format.",
      ),
    content: z
      .string()
      .min(1)
      .max(config.max_content_chars)
      .describe(
        `The complete document as Markdown (at most ${config.max_content_chars} characters): headings (#, ##, ###), paragraphs, **bold**, *italic*, bullet and numbered lists, task lists (- [ ]), tables, > quotes, code blocks, links. In docx and pdf a line with only <!-- pagebreak --> starts a new page. To show an image, in any format, first declare it in images with an ID, then put ![descriptive alt text](image:ID) on its own line where it belongs; an ID that images does not declare fails the call. A Markdown document you revise already holds its images as ![alt text](eneo-file:…) lines: keep those lines exactly as they are, and when you make a Word or PDF file from it also list each in images with that eneo-file value as its url. Do not put signed URLs in the Markdown. Images are static in exported documents.`,
      ),
    images: z
      .array(
        imageReference
          .extend({
            id: z
              .string()
              .regex(/^[A-Za-z][A-Za-z0-9_-]{0,63}$/)
              .optional()
              .describe(
                "The ID its ![alt text](image:ID) line uses. Leave out only for an image the content already places with its own eneo-file line.",
              ),
            caption: z.string().min(1).max(500).optional(),
            width_percent: z
              .number()
              .min(25)
              .max(100)
              .default(100)
              .describe(
                "Percentage of the available page width, 25–100. Aspect ratio is preserved and tall images are reduced to fit the page.",
              ),
          })
          .strict(),
      )
      .max(8)
      .optional()
      .describe(
        "Existing PNG/JPEG attachments, images generated in the conversation (generate_image) or chart images to show in the document, using their current signed reference URLs. Works in every format: adding an image to a Markdown document keeps it Markdown. Place each at a standalone ![alt text](image:ID) in content; caption is printed below it. Reuse existing images; if only an interactive chart exists, export it with create_chart format=png and display=none first. Do not recreate images already available.",
      ),
    filename,
    language: z
      .enum(["sv", "en"])
      .default("sv")
      .describe("Language of the document (footer and metadata)."),
    template: documentReference
      .optional()
      .describe(
        "A Word template from the conversation, when the user names one or attaches one for that purpose: the signed url and filename of the .docx. Leave it out otherwise: Eneo applies the organisation's document template on its own. The content is rendered into the template in its own styles, keeping its headers, footers and page setup. The document goes into a rich content control tagged content (or dokument), else where a paragraph reads {{content}}, else in place of the template's body. Only with format docx.",
      ),
    fields: placeholderValues(config.max_content_chars)
      .optional()
      .describe(
        "Only with a template that has other fields besides the content, for example a text control or {{diarienummer}} in its header: the plain-text value for each, by its tag or name without the braces. Title, date, year and organisation are filled by Eneo. Every other field needs a value; an empty string leaves a {{placeholder}} blank and removes a content control.",
      ),
    revises: earlierDocumentReference
      .optional()
      .describe(
        "To change a document created earlier in this conversation: its signed url and filename, from the reference url you were given for it. Pass the complete revised content. The new file replaces it: a Word file keeps its layout and template, and the filename is reused unless you give another.",
      ),
  });
  const editInput = z.object({
    revises: earlierMarkdownReference.describe(
      "The Markdown document to change: its signed url and filename, from the reference url you were given for it.",
    ),
    edits: z
      .array(documentEdit)
      .min(1)
      .max(MAX_EDITS)
      .describe(
        "The changes, applied in order: for each, the exact text to find in the document and the text that replaces it.",
      ),
  });
  const fillInput = z.object({
    template: templateReference.describe(
      "The template: the signed url and filename of a .docx, .txt or .md file attached in the conversation or by the assistant.",
    ),
    inspect: z
      .boolean()
      .optional()
      .describe(
        "true to only list the template's fields (name, label, kind, guidance text) without producing a file. Use it first when you do not know a template's fields.",
      ),
    values: placeholderValues(config.max_content_chars)
      .optional()
      .describe(
        'The value for each field, by its tag or name without the braces, e.g. {"namn": "Anna Berg"}. A text field and a {{placeholder}} take plain text, where a line break starts a new line; a rich content control takes a document in Markdown (headings, lists, tables). An empty string leaves a {{placeholder}} blank and removes a content control. Required unless inspect is true.',
      ),
    filename,
  });
  return [
    {
      name: "create_document",
      title: "Create document",
      description:
        "Create a document from Markdown: a Markdown document (md) shown beside the conversation, or a Word (.docx) or PDF file to download. Use md for working material the user reads and revises in Eneo: a plan, a summary, notes, a draft, an outline. Create one without being asked when your answer would otherwise be a long standalone piece the user will keep or keep working on, and then answer with a short note; short answers and plain questions stay in the message. Use docx for a document that leaves Eneo (a report, letter, memo, tjänsteskrivelse, anything asked for 'as Word') and pdf when the user asks for one. Write the complete, well-structured content in Markdown with headings, lists and tables. To put a chart or picture in a document, in any format, pass the existing PNG/JPEG reference in images and place it with a standalone image:ID Markdown marker, with a caption. A Markdown document stays Markdown when an image is added: never switch to Word or PDF for the image's sake, only when the user asks for that file. Interactive charts need a PNG export first; use display=none for images only needed by the document. Eneo applies the organisation's document template to Word files on its own; pass template only when the user names a Word template or attaches one for that purpose, and output docx. If the template is a form with fields to fill in (content controls or {{placeholders}}) rather than a layout for a whole document, use fill_template instead. To change part of a Markdown document you created earlier, use edit_document. To restructure or rewrite a document, or to change a Word or PDF file, pass it as revises with the full revised content; the result replaces it. Mention the document by name and do not paste its content back.",
      inputSchema: input.shape,
      readOnly: false,
      async execute(raw, ctx) {
        const args = input.parse(raw);
        // A revision stays in the earlier document's format unless another is asked for.
        const earlierFormat = args.revises?.filename.split(".").pop()!.toLowerCase() as
          "md" | "docx" | "pdf" | undefined;
        const format = args.format ?? (args.template ? "docx" : (earlierFormat ?? "md"));
        if (args.template && format !== "docx")
          throw new ToolError("TEMPLATE_FORMAT", "A template applies to Word (docx) output only.");
        const images = args.images ?? [];
        const ids = images.flatMap((image) => image.id ?? []);
        if (new Set(ids).size !== ids.length)
          throw new ToolError("INVALID_IMAGES", "Image IDs must be unique.");
        const sources: Buffer[] = [];
        // The layout comes from the template, else from the Word file being revised, whose
        // own layout (and the template it was made from) carries over to the new version.
        const layout =
          args.template ??
          (earlierFormat === "docx" && format === "docx" ? args.revises : undefined);
        if (args.fields && !args.template)
          throw new ToolError(
            "FIELDS_WITHOUT_TEMPLATE",
            "fields fill a template's {{placeholders}}; pass them together with template.",
          );
        const name = safeFilename(
          args.filename ?? (args.revises ? stem(args.revises.filename) : args.title),
          format,
        );
        // Every declared image is downloaded, so Eneo checks access to it for this call.
        const imageFiles = [];
        let imageBytes = 0;
        for (const image of images) {
          const handle = fileHandle(image);
          const { bytes } = await fetchReference(image, ctx, {
            ...access,
            maxBytes: Math.min(access.maxBytes, 10 * 1024 * 1024),
          });
          imageBytes += bytes.length;
          if (imageBytes > 32 * 1024 * 1024)
            throw new ToolError("IMAGES_TOO_LARGE", "Document images must total at most 32 MiB.");
          imageFiles.push({ ...image, handle: handle!, bytes });
        }
        if (format === "md") {
          // The file is the content itself, under its title, with each image named by its
          // file handle. Nothing is rendered, and the content limit keeps it well below
          // the export limit.
          if (imageFiles.some((image) => !isRaster(image.bytes)))
            throw new ToolError("INVALID_IMAGES", "Use a valid PNG or JPEG image.");
          const content = placeImages(args.content, imageFiles);
          const text = /^\s*# /.test(content) ? content : `# ${args.title}\n\n${content}`;
          return deliver(
            "md",
            name,
            Buffer.from(text.endsWith("\n") ? text : `${text}\n`, "utf8"),
            undefined,
            args.revises?.filename,
          );
        }
        if (layout) sources.push((await fetchReference(layout, ctx, access)).bytes);
        const imageSources = [];
        for (const image of imageFiles) {
          imageSources.push({
            id: image.id,
            handle: image.handle,
            caption: image.caption,
            widthPercent: image.width_percent,
            index: sources.length,
          });
          sources.push(image.bytes);
        }
        return produce(
          render,
          config,
          format,
          name,
          {
            kind: "markdown",
            title: args.title,
            content: args.content,
            language: args.language,
            images: imageSources,
            ...(layout ? { template: { index: 0 } } : {}),
            ...(args.fields ? { fields: args.fields } : {}),
          },
          sources,
          args.revises?.filename,
        );
      },
    },
    {
      name: "edit_document",
      title: "Edit document",
      description:
        "Change part of a Markdown document you created earlier in this conversation: a sentence, a paragraph, a list item, a table row, or a passage the user quoted. Pass the document as revises and each change as the exact text to find and its replacement. The rest of the document stays exactly as it is, and the result replaces the earlier version beside the conversation. When the text occurs more than once, pass occurrence; a quoted passage says which occurrence it is. To restructure or rewrite the document, and for Word and PDF files, use create_document with revises instead. Mention the document by name and do not paste its content back.",
      inputSchema: editInput.shape,
      readOnly: false,
      async execute(raw, ctx) {
        const args = editInput.parse(raw);
        const earlier = await fetchReference(args.revises, ctx, access);
        const text = applyEdits(
          earlier.bytes.toString("utf8"),
          args.edits,
          config.max_content_chars,
        );
        return deliver(
          "md",
          safeFilename(stem(args.revises.filename), "md"),
          Buffer.from(text, "utf8"),
          undefined,
          args.revises.filename,
        );
      },
    },
    {
      name: "fill_template",
      title: "Fill template",
      description:
        "Fill in a template the user or the assistant supplied: a Word (.docx) file with content controls (fields with a tag, as Word's Developer tab makes them) or {{placeholders}} such as {{namn}} or {{datum}}, or a plain text (.txt) or Markdown (.md) file with {{placeholders}}. Call it with inspect=true first to see the fields: each has a name, a label and often guidance text saying what to write; a rich field takes a document in Markdown, a text field one value. Then pass a value for every field; the result is the same file with the values in place, in the template's own format and layout. If a value is missing the call fails and lists the fields, so you can ask the user for what you do not know. A PDF cannot be filled: ask for the Word original. To write a whole document into a Word template instead, use create_document. The file is attached to your answer for the user to download: mention it by name and do not paste its content back.",
      inputSchema: fillInput.shape,
      readOnly: false,
      async execute(raw, ctx) {
        const args = fillInput.parse(raw);
        const format = args.template.filename.split(".").pop()!.toLowerCase() as
          "docx" | "txt" | "md";
        const template = await fetchReference(args.template, ctx, access);
        if (args.inspect) {
          const report: TemplateReport =
            format === "docx"
              ? await (
                  inspect ??
                  (() => {
                    throw new ToolError(
                      "INSPECT_UNAVAILABLE",
                      "Template inspection is not available on this runtime.",
                    );
                  })
                )(template.bytes)
              : textReport(template.bytes);
          return {
            template: args.template.filename,
            ...report,
            next: report.placeholders.some((p) => p.supported)
              ? "Call fill_template again with a value for every supported field."
              : "This template has no fields to fill. To write a whole document into it, use create_document with it as the template.",
          };
        }
        if (!args.values)
          throw new ToolError(
            "VALUES_REQUIRED",
            "Pass values for the template's fields, or inspect=true to list them.",
          );
        return produce(
          render,
          config,
          format,
          safeFilename(args.filename ?? stem(args.template.filename), format),
          { kind: "fill", template: { index: 0 }, values: args.values },
          [template.bytes],
        );
      },
    },
  ];
}

export function spreadsheetTools(
  config: DocumentConfig,
  render: Renderer,
  access: ReferenceAccess,
): ToolDefinition[] {
  const input = z.object({
    title: z.string().min(1).max(200),
    sheets: z
      .array(
        z
          .object({
            name: z
              .string()
              .min(1)
              .max(31)
              .describe("Sheet name (Excel rules: at most 31 characters, no []:*?/\\)."),
            columns: z
              .array(z.string().max(200))
              .min(1)
              .max(64)
              .optional()
              .describe("Header row, for a sheet given as rows."),
            rows: z
              .array(z.array(cell).max(64))
              .max(5000)
              .optional()
              .describe("Data rows in column order; numbers as numbers so Excel can calculate."),
            source: fileReference
              .extend({
                sheet: z
                  .string()
                  .max(200)
                  .optional()
                  .describe("Sheet of an XLSX source; required when it has several."),
              })
              .strict()
              .optional()
              .describe(
                "Instead of columns and rows: a CSV or XLSX file to copy as this sheet, by its signed url and filename (for example the export of query_table). Use this for anything larger than a small table.",
              ),
          })
          .refine((sheet) => (sheet.source ? !sheet.columns && !sheet.rows : !!sheet.columns), {
            message: "Give each sheet either a source file, or columns and rows",
          }),
      )
      .min(1)
      .max(10),
    filename,
    revises: earlierWorkbookReference
      .optional()
      .describe(
        "To change a workbook created earlier in this conversation: its signed url and filename, from the reference url you were given for it. Give the sheets that stay as source from that same url (naming each sheet) and the changed ones inline. The new file replaces it and reuses the filename unless you give another.",
      ),
  });
  return [
    {
      name: "create_spreadsheet",
      title: "Create spreadsheet",
      description:
        "Produce an Excel workbook (.xlsx) from one or more tables. Give each sheet a name and either columns and rows (small tables you compiled, numbers as numbers) or a source file: the signed url of a CSV or XLSX, such as the export from query_table, so large results never pass through your context. Text is always stored as text (a value starting with = is not a formula). This creates a new table workbook, not a faithful edit of an arbitrary Excel workbook: source formulas and original formatting are not preserved and formulas are not recalculated. The first row is frozen and bold. To change a workbook you created earlier, pass it as revises; the result replaces it. The file is attached to your answer for the user to download: mention it by name and do not repeat the rows.",
      inputSchema: input.shape,
      readOnly: false,
      async execute(raw, ctx) {
        const args = input.parse(raw);
        const sources: Buffer[] = [];
        const sheets: SheetRequest[] = [];
        for (const sheet of args.sheets) {
          if (!sheet.source) {
            sheets.push({
              name: sheet.name,
              columns: sheet.columns,
              rows: sheet.rows ?? [],
            });
            continue;
          }
          const file = await fetchReference(sheet.source, ctx, access);
          sources.push(file.bytes);
          sheets.push({
            name: sheet.name,
            source: {
              index: sources.length - 1,
              isXlsx: file.isXlsx,
              ...(sheet.source.sheet ? { sheet: sheet.source.sheet } : {}),
            },
          });
        }
        return produce(
          render,
          config,
          "xlsx",
          safeFilename(
            args.filename ?? (args.revises ? stem(args.revises.filename) : args.title),
            "xlsx",
          ),
          { kind: "sheets", title: args.title, sheets },
          sources,
          args.revises?.filename,
        );
      },
    },
  ];
}
