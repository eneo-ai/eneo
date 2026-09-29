import type { ExportFormat } from "./config";

export type Cell = string | number | boolean | null;
/** A sheet as the XLSX engine renders it. */
export type SheetSpec = {
  name: string;
  columns: string[];
  rows: Cell[][];
};
export type DocumentSpec =
  | { kind: "markdown"; title: string; content: string; language: "sv" | "en" }
  | { kind: "sheets"; title: string; sheets: SheetSpec[] };

/**
 * A sheet read from a downloaded CSV or XLSX file instead of inline rows. `index` points into
 * the render request's sources; the renderer fills in `path`, a file in its own directory.
 */
export type SheetSource = { index: number; isXlsx: boolean; sheet?: string; path?: string };
export type SheetRequest = {
  name: string;
  columns?: string[];
  rows?: Cell[][];
  source?: SheetSource;
};
/** What a render job asks for: inline content, or sheets still to be read from files. */
export type DocumentRequest =
  | Extract<DocumentSpec, { kind: "markdown" }>
  | { kind: "sheets"; title: string; sheets: SheetRequest[] };

/** Child job: render one document and write its bytes to `outputPath` (a parent-owned file). */
export type RenderJob = {
  kind: "render_document";
  format: ExportFormat;
  document: DocumentRequest;
  outputPath: string;
  maxBytes: number;
  organisationName?: string;
};
export type RenderResult = { bytes: number; pages?: number };
