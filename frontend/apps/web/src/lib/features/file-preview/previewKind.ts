/** The renderer a file is previewed with. */
export type PreviewKind = "docx" | "pdf" | "xlsx" | "csv" | "tsv" | "markdown" | "text";

/** What a preview needs to know about a file; satisfied by `FilePublic`. */
export type PreviewFile = {
  id: string;
  name: string;
  mimetype: string;
  size: number;
  original_size?: number | null;
};

const KIND_BY_MIMETYPE: Record<string, PreviewKind> = {
  "application/vnd.openxmlformats-officedocument.wordprocessingml.document": "docx",
  "application/pdf": "pdf",
  "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": "xlsx",
  "text/csv": "csv",
  "text/tab-separated-values": "tsv",
  "text/markdown": "markdown",
  "text/plain": "text",
  "application/json": "text"
};

const KIND_BY_EXTENSION: Record<string, PreviewKind> = {
  docx: "docx",
  pdf: "pdf",
  xlsx: "xlsx",
  csv: "csv",
  tsv: "tsv",
  md: "markdown",
  markdown: "markdown",
  txt: "text",
  json: "text"
};

/**
 * The renderer for a file, or null when it has none and can only be downloaded.
 *
 * The extension decides first: browsers report text files under loose types (a
 * `.md` or `.csv` upload often arrives as `text/plain`), while the name says
 * what the file is.
 */
export function previewKindOf(file: { name: string; mimetype: string }): PreviewKind | null {
  const dot = file.name.lastIndexOf(".");
  const extension = dot > 0 ? file.name.slice(dot + 1).toLowerCase() : "";
  const mimetype = file.mimetype.split(";")[0].trim().toLowerCase();
  return KIND_BY_EXTENSION[extension] ?? KIND_BY_MIMETYPE[mimetype] ?? null;
}
