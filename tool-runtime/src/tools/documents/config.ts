import { z } from "zod";

// txt and md are only produced by filling a template of that format.
export const FORMATS = ["docx", "xlsx", "pdf", "txt", "md"] as const;
export type ExportFormat = (typeof FORMATS)[number];
export const documentConfigSchema = z
  .object({
    // The rendered file; Eneo admits generated files up to MCP_TOOL_FILE_MAX_BYTES (20 MiB).
    max_export_bytes: z
      .number()
      .int()
      .min(256 * 1024)
      .max(20 * 1024 * 1024)
      .default(10 * 1024 * 1024),
    // Markdown characters per document; the runtime's request-body cap follows this
    // (DOCUMENT_MAX_CONTENT_CHARS), so JSON-escaped text always fits.
    max_content_chars: z.number().int().min(5000).max(1_000_000).default(50_000),
    organisation_name: z.string().max(120).optional(),
  })
  .strict();
export type DocumentConfig = z.infer<typeof documentConfigSchema>;
