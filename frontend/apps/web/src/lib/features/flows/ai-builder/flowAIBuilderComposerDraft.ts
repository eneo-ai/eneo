/**
 * Per-session refinement-composer draft record (handoff §2): text plus
 * references to completed-but-unsent uploads. Persisted in localStorage so a
 * draft survives pane/mode switches, failed sends and reloads. Queued or
 * in-flight binary uploads are NOT persisted — only completed server files
 * have a durable identity.
 */

export interface ComposerDraftFile {
  id: string;
  name: string;
  size: number;
  mimetype: string;
}

export interface ComposerDraft {
  text: string;
  files: ComposerDraftFile[];
}

const KEY_PREFIX = "eneo:ai-builder:draft:";

function keyFor(sessionId: string): string {
  return `${KEY_PREFIX}${sessionId}`;
}

function isDraftFile(value: unknown): value is ComposerDraftFile {
  if (typeof value !== "object" || value === null) return false;
  const file = value as Record<string, unknown>;
  return (
    typeof file.id === "string" &&
    typeof file.name === "string" &&
    typeof file.size === "number" &&
    typeof file.mimetype === "string"
  );
}

export function loadComposerDraft(sessionId: string): ComposerDraft | null {
  let raw: string | null;
  try {
    raw = localStorage.getItem(keyFor(sessionId));
  } catch {
    return null;
  }
  if (!raw) return null;
  try {
    const parsed = JSON.parse(raw) as unknown;
    if (typeof parsed !== "object" || parsed === null) return null;
    const draft = parsed as Record<string, unknown>;
    const text = typeof draft.text === "string" ? draft.text : "";
    const files = Array.isArray(draft.files) ? draft.files.filter(isDraftFile) : [];
    if (text.length === 0 && files.length === 0) return null;
    return { text, files };
  } catch {
    return null;
  }
}

export function saveComposerDraft(sessionId: string, draft: ComposerDraft): void {
  try {
    if (draft.text.length === 0 && draft.files.length === 0) {
      localStorage.removeItem(keyFor(sessionId));
    } else {
      localStorage.setItem(keyFor(sessionId), JSON.stringify(draft));
    }
  } catch {
    // Quota/permission failures degrade to session-only drafts.
  }
}

export function clearComposerDraft(sessionId: string): void {
  try {
    localStorage.removeItem(keyFor(sessionId));
  } catch {
    // Already absent or storage unavailable — nothing to clear.
  }
}
