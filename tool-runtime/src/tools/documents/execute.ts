// Runs inside sandbox children only; the document libraries never load in the parent.
import { writeFile } from "node:fs/promises";
import { ToolError } from "../../errors";
import { RenderError, renderDocument } from "./engine/render";
import type { RenderJob, RenderResult } from "./ports";

export async function executeRender(job: RenderJob): Promise<RenderResult> {
  let rendered;
  try {
    rendered = await renderDocument(job.format, job.document, {
      organisationName: job.organisationName,
    });
  } catch (error) {
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
