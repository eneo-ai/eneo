/** A preview of actual streamed input; it is not the finished file. */
export type DocumentDraft = {
  callId: string;
  title: string;
  text: string;
  /** Keep a labelled earlier draft visible while a replacement starts streaming. */
  showingPreviousDraft?: boolean;
  sheets?: {
    name: string;
    columns: string[];
    rows: string[][];
    fromSource: boolean;
    truncated: boolean;
  }[];
};

export type DraftToolCall = {
  toolCallId: string;
  purpose: string | null;
  approved: boolean | null;
  resultStatus: string | null;
};

const textOf = (value: unknown): string => (typeof value === "string" ? value : "");
const objectOf = (value: unknown): Record<string, unknown> =>
  value && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : {};
const cellOf = (value: unknown): string =>
  typeof value === "string" || typeof value === "number" || typeof value === "boolean"
    ? String(value)
    : "";

/**
 * The document a file-creation call is writing, from its arguments so far.
 * Null once the call has a file, was refused, or has finished without one.
 */
export function documentDraft(
  call: DraftToolCall,
  args: Record<string, unknown> | undefined,
  hasFile: boolean
): DocumentDraft | null {
  if (call.purpose !== "file_creation" || hasFile || call.approved === false) return null;
  if (call.resultStatus && !["pending", "approved"].includes(call.resultStatus)) return null;
  const input = args ?? {};
  const title = textOf(input.title);
  // Image markers refer to assets embedded by the document tool. They are not
  // browser URLs; show their descriptions until the finished file arrives.
  const content = textOf(input.content).replace(/^!\[([^\]]*)\]\(image:[^)]+\)\s*$/gm, "$1");
  const sheets = Array.isArray(input.sheets)
    ? input.sheets.slice(0, 32).map((item) => {
        const sheet = objectOf(item);
        return {
          name: textOf(sheet.name),
          columns: Array.isArray(sheet.columns) ? sheet.columns.slice(0, 64).map(textOf) : [],
          rows: Array.isArray(sheet.rows)
            ? sheet.rows
                .slice(0, 100)
                .filter(Array.isArray)
                .map((row) => row.slice(0, 64).map(cellOf))
            : [],
          fromSource: !!sheet.source,
          truncated: Array.isArray(sheet.rows) && sheet.rows.length > 100
        };
      })
    : undefined;
  return {
    callId: call.toolCallId,
    title,
    text: /^\s*# /.test(content) || !title || !content ? content : `# ${title}\n\n${content}`,
    sheets
  };
}
