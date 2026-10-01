import { mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { z } from "zod";
import { ToolError } from "../../errors";
import {
  documentReference,
  earlierDocumentReference,
  earlierWorkbookReference,
  fetchReference,
  fileReference,
  type ReferenceAccess,
} from "../files/reference";
import { RichResult, type ToolDefinition } from "../types";
import type { DocumentConfig, ExportFormat } from "./config";
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
        request.document.kind === "markdown"
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
  return new RichResult(
    {
      filename: name,
      format,
      bytes: buffer.length,
      ...(pages !== undefined ? { pages } : {}),
      ...(replaces ? { replaces } : {}),
      delivered: replaces
        ? `The file is attached to this answer for the user to download and replaces ${replaces}. Say so, mention it by name; do not paste its content or invent a link.`
        : "The file is attached to this answer for the user to download. Mention it by name; do not paste its content or invent a link.",
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
    content: z
      .string()
      .min(1)
      .max(config.max_content_chars)
      .describe(
        `The complete document as Markdown (at most ${config.max_content_chars} characters): headings (#, ##, ###), paragraphs, **bold**, *italic*, bullet and numbered lists, tables, > quotes, code blocks, links. A line with only <!-- pagebreak --> starts a new page. Images are not supported.`,
      ),
    format: z.enum(["docx", "pdf"]).default("docx").describe("Output format: docx or pdf."),
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
    revises: earlierDocumentReference
      .optional()
      .describe(
        "To change a document created earlier in this conversation: its signed url and filename, from the reference url you were given for it. Pass the complete revised content. The new file replaces it: a Word file keeps its layout and template, and the filename is reused unless you give another.",
      ),
  });
  return [
    {
      name: "create_document",
      title: "Create document",
      description:
        "Produce a real document (Word .docx or PDF) from Markdown. Use it when the user asks for a document, report, memo, letter, tjänsteskrivelse or 'as Word/PDF'; write the complete, well-structured content in Markdown with headings, lists and tables. When the user names a Word template or one is attached for that purpose, pass its signed url as template and output docx. To change a document you created earlier, pass it as revises with the full revised content; the result replaces it. The file is attached to your answer for the user to download: mention it by name and do not paste the whole content back.",
      inputSchema: input.shape,
      readOnly: false,
      async execute(raw, ctx) {
        const args = input.parse(raw);
        if (args.template && args.format !== "docx")
          throw new ToolError("TEMPLATE_FORMAT", "A template applies to Word (docx) output only.");
        const sources: Buffer[] = [];
        // The layout comes from the template, else from the Word file being revised, whose
        // own layout (and the template it was made from) carries over to the new version.
        const earlierIsDocx = args.revises?.filename.toLowerCase().endsWith(".docx") ?? false;
        const layout =
          args.template ?? (earlierIsDocx && args.format === "docx" ? args.revises : undefined);
        if (layout) sources.push((await fetchReference(layout, ctx, access)).bytes);
        return produce(
          render,
          config,
          args.format,
          safeFilename(
            args.filename ?? (args.revises ? stem(args.revises.filename) : args.title),
            args.format,
          ),
          {
            kind: "markdown",
            title: args.title,
            content: args.content,
            language: args.language,
            ...(layout ? { template: { index: 0 } } : {}),
          },
          sources,
          args.revises?.filename,
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
        "Produce an Excel workbook (.xlsx) from one or more tables. Give each sheet a name and either columns and rows (small tables you compiled, numbers as numbers) or a source file: the signed url of a CSV or XLSX, such as the export from query_table, so large results never pass through your context. Text is always stored as text (a value starting with = is not a formula). The first row is frozen and bold. To change a workbook you created earlier, pass it as revises; the result replaces it. The file is attached to your answer for the user to download: mention it by name and do not repeat the rows.",
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
