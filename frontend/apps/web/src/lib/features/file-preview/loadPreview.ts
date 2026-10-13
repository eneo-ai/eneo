import { parseDelimited } from "./delimited";
import type { PreviewFile, PreviewKind } from "./previewKind";

export type PreviewCell = string | number | boolean | Date | null;

export type PreviewSheet = {
  name: string;
  /** The leading rows, capped for rendering; the first is the header. */
  rows: PreviewCell[][];
  /** Rows in the whole sheet, or null when only the start of the file was read. */
  totalRows: number | null;
};

export type PreviewContent =
  | { kind: "docx"; bytes: ArrayBuffer }
  | { kind: "pdf"; blob: Blob }
  | { kind: "table"; sheets: PreviewSheet[] }
  | { kind: "markdown" | "text"; text: string; truncated: boolean };

/** The file is larger than its format can be previewed at. */
export class PreviewTooLargeError extends Error {}

const MEGABYTE = 1024 * 1024;
// Formats that must be read whole are refused above these sizes; parsing a
// larger file would stall the page for a preview nobody scrolls through.
const WHOLE_FILE_LIMIT: Partial<Record<PreviewKind, number>> = {
  docx: 25 * MEGABYTE,
  pdf: 50 * MEGABYTE,
  xlsx: 8 * MEGABYTE
};
// Text formats show their beginning instead: the download stops here.
const TEXT_PREFIX_BYTES = 2 * MEGABYTE;
// A table renders at most this many cells, and never more than MAX_ROWS rows.
const MAX_ROWS = 500;
const MAX_CELLS = 20_000;

function capRows<T extends unknown[]>(rows: T[]): T[] {
  const columns = rows.reduce((widest, row) => Math.max(widest, row.length), 1);
  const limit = Math.max(50, Math.min(MAX_ROWS, Math.floor(MAX_CELLS / columns)));
  return rows.length > limit ? rows.slice(0, limit) : rows;
}

/** Reads at most `limit` bytes of the body, cancelling the download beyond it. */
async function readPrefix(
  response: Response,
  limit: number
): Promise<{ bytes: Uint8Array; truncated: boolean }> {
  const reader = response.body!.getReader();
  const chunks: Uint8Array[] = [];
  let length = 0;
  let truncated = false;
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    chunks.push(value);
    length += value.length;
    if (length >= limit) {
      truncated = true;
      await reader.cancel();
      break;
    }
  }
  const bytes = new Uint8Array(length);
  let offset = 0;
  for (const chunk of chunks) {
    bytes.set(chunk, offset);
    offset += chunk.length;
  }
  return { bytes, truncated };
}

/** UTF-8, else Windows-1252: what a spreadsheet on Windows saves a CSV as. */
function decodeText(bytes: Uint8Array, truncated: boolean): string {
  try {
    // A cut in the middle of a character is not an encoding error: `stream`
    // holds the incomplete tail back instead of failing on it.
    return new TextDecoder("utf-8", { fatal: true }).decode(bytes, { stream: truncated });
  } catch {
    return new TextDecoder("windows-1252").decode(bytes);
  }
}

async function loadText(response: Response) {
  const { bytes, truncated } = await readPrefix(response, TEXT_PREFIX_BYTES);
  return { text: decodeText(bytes, truncated), truncated };
}

async function loadDelimited(response: Response, delimiter?: string): Promise<PreviewContent> {
  const { text, truncated } = await loadText(response);
  const rows = parseDelimited(text, delimiter);
  // The last record of a cut-off file is incomplete.
  if (truncated) rows.pop();
  return {
    kind: "table",
    sheets: [{ name: "", rows: capRows(rows), totalRows: truncated ? null : rows.length }]
  };
}

async function loadWorkbook(response: Response): Promise<PreviewContent> {
  const [{ default: readXlsxFile }, bytes] = await Promise.all([
    import("read-excel-file/browser"),
    response.arrayBuffer()
  ]);
  const sheets = await readXlsxFile(bytes);
  return {
    kind: "table",
    sheets: sheets.map(({ sheet, data }) => ({
      name: sheet,
      rows: capRows(data) as PreviewCell[][],
      totalRows: data.length
    }))
  };
}

/**
 * Downloads a file's exact bytes from its signed URL and prepares them for the
 * renderer of `kind`. Nothing is rendered here; the result is plain data.
 */
export async function loadPreview(
  file: PreviewFile,
  kind: PreviewKind,
  url: string,
  signal: AbortSignal
): Promise<PreviewContent> {
  const limit = WHOLE_FILE_LIMIT[kind];
  if (limit !== undefined && (file.original_size ?? file.size) > limit) {
    throw new PreviewTooLargeError();
  }
  const response = await fetch(url, { signal });
  if (!response.ok || !response.body) throw new Error(`Preview download failed`);

  switch (kind) {
    case "docx":
      return { kind, bytes: await response.arrayBuffer() };
    case "pdf":
      // Typed here rather than trusted from the response: the viewer is chosen
      // by the blob's type.
      return { kind, blob: new Blob([await response.arrayBuffer()], { type: "application/pdf" }) };
    case "xlsx":
      return loadWorkbook(response);
    case "csv":
      return loadDelimited(response);
    case "tsv":
      return loadDelimited(response, "\t");
    case "markdown":
    case "text":
      return { kind, ...(await loadText(response)) };
  }
}
