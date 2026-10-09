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
      if (format === "docx") {
        const { fillTemplateDocx } = await import("./word/apply");
        return fillTemplateDocx(options.template!, document.values);
      }
      const { fillText } = await import("./fill");
      return fillText(options.template!, document.values);
    });
    if (!filled.placeholders.length)
      throw new RenderError(
        "The template has no content controls or {{placeholders}} to fill. To write a whole document into it, call create_document with it as the template.",
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
    // Every Word file is rendered into a template: the one given, else Eneo's own.
    return wordErrors(async () => {
      const { renderIntoTemplate } = await import("./word/apply");
      const { builtinTemplate } = await import("./word/builtin");
      const template = options.template ?? (await builtinTemplate(document.language));
      return {
        buffer: await renderIntoTemplate(template, document, {
          images,
          organisationName: options.organisationName,
        }),
      };
    });
  }
  if (options.template) throw new RenderError("A template applies to Word (docx) output only.");
  if (format !== "pdf") throw new RenderError("A document is rendered as docx or pdf.");
  const { renderPdf } = await import("./pdf");
  return renderPdf(document, { ...options, images });
}

/** A template that is not a usable Word file is a render failure the caller can read. */
async function wordErrors<T>(work: () => Promise<T>): Promise<T> {
  const { TemplateError } = await import("./word/inspect");
  try {
    return await work();
  } catch (error) {
    if (error instanceof TemplateError) throw new RenderError(error.message);
    throw error;
  }
}
