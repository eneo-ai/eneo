// Rendering runs in sandbox children only: the document libraries are loaded lazily per format
// and never imported by the tool entrypoint (tool.ts).
import type { ExportFormat } from "../config";
import type { DocumentSpec } from "../ports";

export class RenderError extends Error {}
export type Rendered = { buffer: Buffer; pages?: number };
export async function renderDocument(
  format: ExportFormat,
  document: DocumentSpec,
  options: { organisationName?: string; template?: Buffer } = {},
): Promise<Rendered> {
  if (document.kind === "fill") {
    if (!options.template) throw new RenderError("Filling needs a template.");
    if (format !== "docx" && format !== "txt" && format !== "md")
      throw new RenderError("Only Word and text templates can be filled.");
    const filled = await wordErrors(async () => {
      const { fillDocx, fillText } = await import("./fill");
      return format === "docx"
        ? fillDocx(options.template!, document.values)
        : fillText(options.template!, document.values);
    });
    if (!filled.placeholders.length)
      throw new RenderError(
        "The template has no {{placeholders}} to fill. To write a whole document into it, call create_document with it as the template.",
      );
    return { buffer: filled.buffer };
  }
  if (format === "xlsx") {
    if (document.kind !== "sheets") throw new RenderError("A spreadsheet needs sheets.");
    const { renderXlsx } = await import("./xlsx");
    return { buffer: await renderXlsx(document) };
  }
  if (document.kind !== "markdown") throw new RenderError("A document needs markdown content.");
  const { loadDocumentImages } = await import("./images");
  const images = await loadDocumentImages(document);
  if (format === "docx") {
    const { renderDocx } = await import("./docx");
    const rendered = await renderDocx(document, { ...options, images });
    const { template } = options;
    if (!template) return { buffer: rendered };
    return wordErrors(async () => {
      const { applyTemplate } = await import("./template");
      const applied = await applyTemplate(rendered, template);
      if (!document.fields) return { buffer: applied };
      const { fillDocx } = await import("./fill");
      return { buffer: (await fillDocx(applied, document.fields)).buffer };
    });
  }
  if (options.template) throw new RenderError("A template applies to Word (docx) output only.");
  if (format !== "pdf") throw new RenderError("A document is rendered as docx or pdf.");
  const { renderPdf } = await import("./pdf");
  return renderPdf(document, { ...options, images });
}

/** A template that is not a usable Word file is a render failure the caller can read. */
async function wordErrors<T>(work: () => Promise<T>): Promise<T> {
  const { TemplateError } = await import("./template");
  try {
    return await work();
  } catch (error) {
    if (error instanceof TemplateError) throw new RenderError(error.message);
    throw error;
  }
}
