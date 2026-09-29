// Rendering runs in sandbox children only: the document libraries are loaded lazily per format
// and never imported by the tool entrypoint (tool.ts).
import type { ExportFormat } from "../config";
import type { DocumentSpec } from "../ports";

export class RenderError extends Error {}
export type Rendered = { buffer: Buffer; pages?: number };
export async function renderDocument(
  format: ExportFormat,
  document: DocumentSpec,
  options: { organisationName?: string } = {},
): Promise<Rendered> {
  if (format === "xlsx") {
    if (document.kind !== "sheets") throw new RenderError("A spreadsheet needs sheets.");
    const { renderXlsx } = await import("./xlsx");
    return { buffer: await renderXlsx(document) };
  }
  if (document.kind !== "markdown") throw new RenderError("A document needs markdown content.");
  if (format === "docx") {
    const { renderDocx } = await import("./docx");
    return { buffer: await renderDocx(document, options) };
  }
  const { renderPdf } = await import("./pdf");
  return renderPdf(document, options);
}
