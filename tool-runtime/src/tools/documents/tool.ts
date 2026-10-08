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
  fileReference,
  imageReference,
  templateReference,
  type ReferenceAccess,
} from "../files/reference";
import { RichResult, type ToolDefinition } from "../types";
import type { DocumentConfig, ExportFormat } from "./config";
import { applyEdits, documentEdit, MAX_EDITS } from "./edits";
import { MIME_BY_FORMAT, safeFilename } from "./filename";
import type { DocumentRequest, RenderJob, RenderResult, SheetRequest } from "./ports";

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

const filename = z
  .string()
  .max(100)
  .optional()
  .describe(
    "File name without extension, e.g. 'Tjänsteskrivelse trygghet'. Defaults to the title.",
  );
const cell = z.union([z.string().max(2000), z.number(), z.boolean(), z.null()]);
/** Plain-text values for a template's {{placeholders}}, by placeholder name. */
const placeholderValues = z
  .record(z.string().min(1).max(200), z.string().max(5000))
  .refine((values) => Object.keys(values).length <= 200, {
    message: "At most 200 values",
  });
/** The name an earlier file was delivered under, without its extension. */
const stem = (filename: string) => filename.replace(/\.[^.]+$/, "");

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
        `The complete document as Markdown (at most ${config.max_content_chars} characters): headings (#, ##, ###), paragraphs, **bold**, *italic*, bullet and numbered lists, task lists (- [ ]), tables, > quotes, code blocks, links. In docx and pdf a line with only <!-- pagebreak --> starts a new page. For docx/pdf images, put ![descriptive alt text](image:ID) on its own line where each image belongs and declare ID in images. Do not put signed URLs in the Markdown. Images are static in exported documents.`,
      ),
    images: z
      .array(
        imageReference
          .extend({
            id: z.string().regex(/^[A-Za-z][A-Za-z0-9_-]{0,63}$/),
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
        "Existing PNG/JPEG attachments or generated chart images, using their current signed reference URLs. Place each at a standalone ![alt text](image:ID) in content; caption is printed below it. Only docx/pdf. Reuse existing images; if only an interactive chart exists, export it with create_chart format=png and display=none first. Do not recreate images already available.",
      ),
    filename,
    language: z
      .enum(["sv", "en"])
      .default("sv")
      .describe("Language of the document (footer and metadata)."),
    template: documentReference
      .optional()
      .describe(
        "Optional Word template: the signed url and filename of a .docx attached in the conversation or by the assistant. The content is rendered into it, keeping its styles, headers, footers and page setup. A paragraph in the template reading {{content}} marks where the content goes; without one the template's body is replaced. Only with format docx.",
      ),
    fields: placeholderValues
      .optional()
      .describe(
        "Only with a template that has other {{placeholders}} besides {{content}}, for example {{diarienummer}} in its header: the plain-text value for each, by name without the braces. Every placeholder needs a value; an empty string leaves one blank.",
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
    values: placeholderValues.describe(
      'The plain-text value for each placeholder, by its name without the braces, e.g. {"namn": "Anna Berg"}. A line break in a value starts a new line. An empty string leaves a placeholder blank.',
    ),
    filename,
  });
  return [
    {
      name: "create_document",
      title: "Create document",
      description:
        "Create a document from Markdown: a Markdown document (md) shown beside the conversation, or a Word (.docx) or PDF file to download. Use md for working material the user reads and revises in Eneo: a plan, a summary, notes, a draft, an outline. Create one without being asked when your answer would otherwise be a long standalone piece the user will keep or keep working on, and then answer with a short note; short answers and plain questions stay in the message. Use docx for a document that leaves Eneo (a report, letter, memo, tjänsteskrivelse, anything asked for 'as Word') and pdf when the user asks for one. Write the complete, well-structured content in Markdown with headings, lists and tables. For Word/PDF reports with charts, embed existing PNG/JPEG references using images and standalone image:ID Markdown markers, with captions. Interactive charts need a PNG export first; use display=none for images only needed by the document. When the user names a Word template or one is attached for that purpose, pass its signed url as template and output docx; if the template only has {{placeholders}} to fill in, use fill_template instead. To change part of a Markdown document you created earlier, use edit_document. To restructure or rewrite a document, or to change a Word or PDF file, pass it as revises with the full revised content; the result replaces it. Mention the document by name and do not paste its content back.",
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
        if (new Set(images.map((image) => image.id)).size !== images.length)
          throw new ToolError("INVALID_IMAGES", "Image IDs must be unique.");
        if (format === "md" && (images.length || /!\[[^\]]*\]\(image:/.test(args.content)))
          throw new ToolError("IMAGE_FORMAT", "Embedded images require format docx or pdf.");
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
        if (format === "md") {
          // The file is the content itself, under its title. Nothing is rendered, and the
          // content limit keeps it well below the export limit.
          const text = /^\s*# /.test(args.content)
            ? args.content
            : `# ${args.title}\n\n${args.content}`;
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
        let imageBytes = 0;
        for (const image of images) {
          const { bytes } = await fetchReference(image, ctx, {
            ...access,
            maxBytes: Math.min(access.maxBytes, 10 * 1024 * 1024),
          });
          imageBytes += bytes.length;
          if (imageBytes > 32 * 1024 * 1024)
            throw new ToolError("IMAGES_TOO_LARGE", "Document images must total at most 32 MiB.");
          imageSources.push({
            id: image.id,
            caption: image.caption,
            widthPercent: image.width_percent,
            index: sources.length,
          });
          sources.push(bytes);
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
        "Fill in a template the user or the assistant supplied: a Word (.docx), plain text (.txt) or Markdown (.md) file with {{placeholders}} such as {{namn}} or {{datum}}. Pass the template's signed url and a plain-text value for every placeholder; the result is the same file with the values in place, in the template's own format and layout. If a value is missing the call fails and lists the template's placeholders, so you can ask the user for what you do not know. A PDF cannot be filled: ask for the Word original. To write a whole document into a Word template instead, use create_document. The file is attached to your answer for the user to download: mention it by name and do not paste its content back.",
      inputSchema: fillInput.shape,
      readOnly: false,
      async execute(raw, ctx) {
        const args = fillInput.parse(raw);
        const format = args.template.filename.split(".").pop()!.toLowerCase() as
          "docx" | "txt" | "md";
        const template = await fetchReference(args.template, ctx, access);
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
