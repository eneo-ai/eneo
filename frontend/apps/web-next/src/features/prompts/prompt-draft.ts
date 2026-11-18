export type PromptDraft =
  | { kind: "manual"; text: string }
  | { kind: "server" | "annotated"; text: string; description: string };

/**
 * Unchanged manual text is a no-op against a server baseline. Between writes,
 * metadata must match the actual payload already in flight.
 */
export function promptDraftsMatch(a: PromptDraft, b: PromptDraft): boolean {
  if (a.text !== b.text) return false;
  if ((a.kind === "manual" && b.kind === "server") || (a.kind === "server" && b.kind === "manual"))
    return true;
  return (a.kind === "manual" ? "" : a.description) === (b.kind === "manual" ? "" : b.description);
}
