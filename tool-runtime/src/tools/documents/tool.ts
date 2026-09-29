import { mkdtemp, readFile, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { z } from "zod";
import { RichResult, type ToolDefinition } from "../types";
import type { DocumentConfig, ExportFormat } from "./config";
import { MIME_BY_FORMAT, safeFilename } from "./filename";
import type { DocumentSpec, RenderJob, RenderResult } from "./ports";

type RenderRequest = Omit<RenderJob, "kind" | "outputPath">;
/** Renders a document and returns its bytes. */
export type Renderer = (request: RenderRequest) => Promise<{ buffer: Buffer; pages?: number }>;

/**
 * Runs a render job (normally in a sandbox child) against an output file in a directory the
 * parent owns, so the document never has to fit through the child's bounded stdout.
 */
export function fileRenderer(run: (job: RenderJob) => Promise<RenderResult>): Renderer {
  return async (request) => {
    const directory = await mkdtemp(join(tmpdir(), "eneo-tool-runtime-render-"));
    try {
      const outputPath = join(directory, "output");
      const result = await run({ kind: "render_document", ...request, outputPath });
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

/** The file travels back as an MCP embedded resource; Eneo saves it in the conversation. */
async function produce(
  render: Renderer,
  config: DocumentConfig,
  format: ExportFormat,
  name: string,
  document: DocumentSpec,
): Promise<RichResult> {
  const { buffer, pages } = await render({
    format,
    document,
    maxBytes: config.max_export_bytes,
    organisationName: config.organisation_name,
  });
  return new RichResult(
    {
      filename: name,
      format,
      bytes: buffer.length,
      ...(pages !== undefined ? { pages } : {}),
      delivered:
        "The file is attached to this answer for the user to download. Mention it by name; do not paste its content or invent a link.",
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

export function documentTools(config: DocumentConfig, render: Renderer): ToolDefinition[] {
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
  });
  return [
    {
      name: "create_document",
      title: "Create document",
      description:
        "Produce a real document (Word .docx or PDF) from Markdown. Use it when the user asks for a document, report, memo, letter, tjänsteskrivelse or 'as Word/PDF'; write the complete, well-structured content in Markdown with headings, lists and tables. The file is attached to your answer for the user to download: mention it by name and do not paste the whole content back. Every call creates a new file; for a revision call again with the full revised content and say which file replaces which.",
      inputSchema: input.shape,
      readOnly: false,
      async execute(raw) {
        const args = input.parse(raw);
        return produce(
          render,
          config,
          args.format,
          safeFilename(args.filename ?? args.title, args.format),
          { kind: "markdown", title: args.title, content: args.content, language: args.language },
        );
      },
    },
  ];
}

export function spreadsheetTools(config: DocumentConfig, render: Renderer): ToolDefinition[] {
  const input = z.object({
    title: z.string().min(1).max(200),
    sheets: z
      .array(
        z.object({
          name: z
            .string()
            .min(1)
            .max(31)
            .describe("Sheet name (Excel rules: at most 31 characters, no []:*?/\\)."),
          columns: z.array(z.string().max(200)).min(1).max(64).describe("Header row."),
          rows: z
            .array(z.array(cell).max(64))
            .max(5000)
            .describe("Data rows in column order; numbers as numbers so Excel can calculate."),
        }),
      )
      .min(1)
      .max(10),
    filename,
  });
  return [
    {
      name: "create_spreadsheet",
      title: "Create spreadsheet",
      description:
        "Produce an Excel workbook (.xlsx) from one or more tables. Use it when the user wants data in Excel: results from query_table or tables you compiled. Give each sheet a name, a header row and data rows with numbers as numbers; text is always stored as text (a value starting with = is not a formula). The first row is frozen and bold. The file is attached to your answer for the user to download: mention it by name and do not repeat all the rows. Every call creates a new file.",
      inputSchema: input.shape,
      readOnly: false,
      async execute(raw) {
        const args = input.parse(raw);
        return produce(render, config, "xlsx", safeFilename(args.filename ?? args.title, "xlsx"), {
          kind: "sheets",
          title: args.title,
          sheets: args.sheets,
        });
      },
    },
  ];
}
