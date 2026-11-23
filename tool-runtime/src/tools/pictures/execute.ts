// Runs inside sandbox children only. The file is parsed and its pages rendered by the Python
// sidecar the runtime image installs (scripts/extract_images.py), spawned inside this child's
// confinement with the job's directory as the only place it may read or write.
import { writeFile } from "node:fs/promises";
import { basename, join } from "node:path";
import { ToolError } from "../../errors";
import { EXTRACT_IMAGES_SCRIPT, pdfAvailable, runSidecar } from "../documents/engine/pdf";
import {
  OUTPUT_DIRECTORY,
  SOURCE_FILE,
  type ExtractImagesJob,
  type ExtractImagesResult,
  type ExtractedPicture,
} from "./ports";

class ExtractionFailed extends Error {}

export async function executeExtractImages(job: ExtractImagesJob): Promise<ExtractImagesResult> {
  if (!(await pdfAvailable()))
    throw new ToolError(
      "EXTRACTION_UNAVAILABLE",
      "Picture extraction is not installed on this runtime (Python sidecar).",
    );
  await writeFile(
    join(job.directory, "job.json"),
    JSON.stringify({
      base_dir: job.directory,
      input_path: join(job.directory, SOURCE_FILE),
      output_dir: join(job.directory, OUTPUT_DIRECTORY),
      kind: job.fileKind,
      offset: job.offset,
      limit: job.limit,
      max_pages: job.maxPages,
      ...(job.page !== undefined ? { page: job.page } : {}),
    }),
    { mode: 0o600 },
  );
  let printed: Record<string, unknown>;
  try {
    // The parser's own message can quote the file, so it is not passed on.
    printed = await runSidecar(EXTRACT_IMAGES_SCRIPT, job.directory, () => new ExtractionFailed());
  } catch (error) {
    if (!(error instanceof ExtractionFailed) && !(error instanceof SyntaxError)) throw error;
    throw new ToolError(
      "EXTRACTION_FAILED",
      "The pictures in this file could not be read. It may be damaged or password-protected.",
    );
  }
  const total = Number(printed.total);
  const listed = Array.isArray(printed.images) ? (printed.images as Record<string, unknown>[]) : [];
  const pictures: ExtractedPicture[] = [];
  for (const image of listed.slice(0, job.limit)) {
    const file = String(image.file ?? "");
    const mimeType = image.mime_type;
    // Only what the script is known to write is read back by the parent.
    if (
      file !== basename(file) ||
      !/^picture-\d+\.(png|jpg)$/.test(file) ||
      (mimeType !== "image/png" && mimeType !== "image/jpeg")
    )
      continue;
    const page = Number(image.page);
    pictures.push({
      file,
      mimeType,
      width: Number(image.width) || 0,
      height: Number(image.height) || 0,
      ...(Number.isInteger(page) && page > 0 ? { page } : {}),
    });
  }
  return {
    total: Number.isInteger(total) && total >= 0 ? total : pictures.length,
    pictures,
  };
}
