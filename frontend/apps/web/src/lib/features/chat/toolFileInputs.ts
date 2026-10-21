import { referencedFileId } from "./fileReference";
export type ToolInputFile = { id: string; name: string; generated: boolean };

/** Resolve input references against conversation files, never an output filename. */
export function toolFileInputs(
  args: unknown,
  known: ReadonlyMap<string, ToolInputFile>
): ToolInputFile[] {
  const found = new Map<string, ToolInputFile>();
  const visit = (value: unknown, depth: number) => {
    if (depth > 12) return;
    if (typeof value === "string") {
      const id = referencedFileId(value);
      const file = id ? known.get(id) : undefined;
      if (file) found.set(file.id, file);
    } else if (Array.isArray(value)) {
      value.forEach((item) => visit(item, depth + 1));
    } else if (value && typeof value === "object") {
      Object.values(value).forEach((item) => visit(item, depth + 1));
    }
  };
  visit(args, 0);
  return [...found.values()];
}

/** Only requested file-creation deliverables take over the document panel. */
export function opensFilePanel(call: { purpose?: string | null } | undefined): boolean {
  return call?.purpose === "file_creation";
}
