import type { ExportFormat } from "./config";

export type SheetSpec = {
  name: string;
  columns: string[];
  rows: (string | number | boolean | null)[][];
};
export type DocumentSpec =
  | { kind: "markdown"; title: string; content: string; language: "sv" | "en" }
  | { kind: "sheets"; title: string; sheets: SheetSpec[] };
/** Child job: render one document and write its bytes to `outputPath` (a parent-owned file). */
export type RenderJob = {
  kind: "render_document";
  format: ExportFormat;
  document: DocumentSpec;
  outputPath: string;
  maxBytes: number;
  organisationName?: string;
};
export type RenderResult = { bytes: number; pages?: number };
