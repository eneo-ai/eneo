// Runs inside sandbox children only; the document libraries never load in the parent.
import { readFile, writeFile } from "node:fs/promises";
import { ToolError } from "../../errors";
import { RenderError, renderDocument } from "./engine/render";
import { resolveSources } from "./sources";
import type {
  BuiltinTemplateJob,
  InspectJob,
  InspectResult,
  RenderJob,
  RenderResult,
} from "./ports";

export async function executeRender(job: RenderJob): Promise<RenderResult> {
  const document = await resolveSources(job.document);
  const template = document.kind === "sheets" ? undefined : document.template;
  const templatePath = template?.path;
  if (template && !templatePath)
    throw new ToolError("RENDER_FAILED", "The template was not downloaded.");
  let rendered;
  try {
    rendered = await renderDocument(job.format, document, {
      organisationName: job.organisationName,
      ...(templatePath ? { template: await readFile(templatePath) } : {}),
    });
  } catch (error) {
    if (error instanceof ToolError) throw error;
    if (error instanceof RenderError) throw new ToolError("RENDER_FAILED", error.message);
    throw new ToolError(
      "RENDER_FAILED",
      "The document could not be rendered. Simplify its structure and retry.",
    );
  }
  if (rendered.buffer.length > job.maxBytes)
    throw new ToolError(
      "EXPORT_TOO_LARGE",
      "The rendered document exceeds the size limit. Shorten it or split it into several documents.",
    );
  await writeFile(job.outputPath, rendered.buffer, { mode: 0o600 });
  return {
    bytes: rendered.buffer.length,
    ...(rendered.pages !== undefined ? { pages: rendered.pages } : {}),
  };
}

export async function executeInspect(job: InspectJob): Promise<InspectResult> {
  const { inspectTemplate, toReport, TemplateError } = await import("./engine/word/inspect");
  try {
    return { inspection: toReport(await inspectTemplate(await readFile(job.templatePath))) };
  } catch (error) {
    if (error instanceof ToolError) throw error;
    if (error instanceof TemplateError) throw new ToolError("INVALID_TEMPLATE", error.message);
    throw new ToolError("INVALID_TEMPLATE", "The template could not be read.");
  }
}

export async function executeBuiltinTemplate(job: BuiltinTemplateJob): Promise<RenderResult> {
  const { builtinTemplate } = await import("./engine/word/builtin");
  const buffer = await builtinTemplate(job.language);
  await writeFile(job.outputPath, buffer, { mode: 0o600 });
  return { bytes: buffer.length };
}
