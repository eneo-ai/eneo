import type { ExportFormat } from "./config";

export type Cell = string | number | boolean | null;
/** A sheet as the XLSX engine renders it. */
export type SheetSpec = {
  name: string;
  columns: string[];
  rows: Cell[][];
};
/**
 * A downloaded file a render job takes as input. `index` points into the render request's
 * sources; the renderer fills in `path`, a file in its own directory.
 */
export type FileSource = { index: number; path?: string };
/** Placed in the content by `id` (an image:ID line) or by `handle` (an eneo-file: line). */
export type DocumentImage = FileSource & {
  id?: string;
  handle?: string;
  caption?: string;
  widthPercent?: number;
};
export type DocumentSpec =
  | {
      kind: "markdown";
      title: string;
      content: string;
      language: "sv" | "en";
      images?: DocumentImage[];
      /** A downloaded Word document the content is rendered into (DOCX output only). */
      template?: FileSource;
      /** Values for the template's other {{placeholders}}, by name. */
      fields?: Record<string, string>;
    }
  | { kind: "sheets"; title: string; sheets: SheetSpec[] }
  /** A downloaded template whose {{placeholders}} are filled; the output keeps its format. */
  | { kind: "fill"; template: FileSource; values: Record<string, string> };

/** A sheet read from a downloaded CSV or XLSX file instead of inline rows. */
export type SheetSource = FileSource & { isXlsx: boolean; sheet?: string };
export type SheetRequest = {
  name: string;
  columns?: string[];
  rows?: Cell[][];
  source?: SheetSource;
};
/** What a render job asks for: inline content, or sheets still to be read from files. */
export type DocumentRequest =
  | Extract<DocumentSpec, { kind: "markdown" | "fill" }>
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
