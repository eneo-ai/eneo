import { useEffect, useState } from "react";

/**
 * Hands a freshly created resource over to its editor. The create button
 * creates the resource with a default name and navigates straight to the
 * editor; the editor then focuses the name field and announces the creation.
 * A module-level set, not a query parameter, so a reload or a shared link
 * never refocuses or re-announces.
 */
export type CreatedResourceKind = "assistant" | "app" | "group-chat";

const pending = new Set<string>();

function key(kind: CreatedResourceKind, id: string): string {
  return `${kind}:${id}`;
}

/** Remember that the editor for this resource opens right after its creation. */
export function markJustCreated(kind: CreatedResourceKind, id: string): void {
  pending.add(key(kind, id));
}

/** Whether the editor for this resource is opening right after its creation. */
export function isJustCreated(kind: CreatedResourceKind, id: string): boolean {
  return pending.has(key(kind, id));
}

/** Forget the mark, once the editor has acted on it. */
export function clearJustCreated(kind: CreatedResourceKind, id: string): void {
  pending.delete(key(kind, id));
}

/**
 * True for the whole life of the editor that opened right after the resource
 * was created, false for any later visit. The mark is read once on mount (so
 * re-renders agree) and cleared when the editor unmounts.
 */
export function useJustCreated(kind: CreatedResourceKind, id: string): boolean {
  const [created] = useState(() => isJustCreated(kind, id));
  useEffect(() => () => clearJustCreated(kind, id), [kind, id]);
  return created;
}
