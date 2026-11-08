import { useCallback, useEffect, useRef, useState, type SetStateAction } from "react";

const PREFIX = "eneo:chat-draft:";
/** Typing is written after this pause, and at once when the page is hidden. */
const WRITE_DELAY_MS = 300;

/**
 * Whose drafts these are: the organisation and the account. The same shared
 * assistant has the same conversation key for everyone, so without it the next
 * person to sign in on this tab would be given the last one's question.
 */
export function chatDraftOwner(tenantId: string, userId: string): string {
  return `${tenantId}.${userId}`;
}

const keyOf = (owner: string, scope: string) => `${PREFIX}${owner}|${scope}`;

function draftKeys(): string[] {
  const keys: string[] = [];
  for (let index = 0; index < sessionStorage.length; index += 1) {
    const key = sessionStorage.key(index);
    if (key?.startsWith(PREFIX)) keys.push(key);
  }
  return keys;
}

/** Every draft of this tab, on sign-out. */
export function clearChatDrafts() {
  try {
    for (const key of draftKeys()) sessionStorage.removeItem(key);
  } catch {
    // Storage blocked: there is nothing kept to clear.
  }
}

/** Drafts of anyone else, and those written before drafts had an owner, are removed, not just ignored. */
function pruneOtherOwners(owner: string) {
  const mine = `${PREFIX}${owner}|`;
  try {
    for (const key of draftKeys()) if (!key.startsWith(mine)) sessionStorage.removeItem(key);
  } catch {
    // Storage blocked: nothing was kept.
  }
}

function read(owner: string, scope: string): string {
  try {
    pruneOtherOwners(owner);
    return sessionStorage.getItem(keyOf(owner, scope)) ?? "";
  } catch {
    return "";
  }
}

function write(owner: string, scope: string, value: string) {
  try {
    if (value.trim()) sessionStorage.setItem(keyOf(owner, scope), value);
    else sessionStorage.removeItem(keyOf(owner, scope));
  } catch {
    // Storage blocked or full: the draft just lives in memory, as before.
  }
}

/**
 * The text typed in the composer, kept for the tab's life (sessionStorage:
 * gone with the tab and never shared, so a question typed on a shared screen
 * does not outlive it) and for the account that typed it (`owner`: the next
 * account on this tab never sees it, and signing out clears it). A question typed and left (a tap on another
 * conversation, "Ny konversation", a reload, a phone that discarded the tab
 * while another app was open) is there again when the conversation is. `scope`
 * names the conversation: partner and session, or "new". Sending empties it.
 *
 * Files are not kept: they are uploaded, not typed.
 */
export function useChatDraft(owner: string, scope: string) {
  const [value, setValue] = useState(() => read(owner, scope));
  const latest = useRef({ owner, scope, value });
  // Written once typing pauses, and when the page goes away or into the background.
  useEffect(() => {
    // This mounted conversation acquired its session id; a different conversation remounts it.
    if (latest.current.scope !== scope) write(latest.current.owner, latest.current.scope, "");
    latest.current = { owner, scope, value };
    // Sending must clear the old draft before session metadata changes its key.
    if (!value.trim()) {
      write(owner, scope, value);
      return;
    }
    const id = setTimeout(() => write(owner, scope, value), WRITE_DELAY_MS);
    return () => clearTimeout(id);
  }, [owner, scope, value]);
  useEffect(() => {
    const flush = () => write(latest.current.owner, latest.current.scope, latest.current.value);
    const onVisibility = () => {
      if (document.visibilityState === "hidden") flush();
    };
    document.addEventListener("visibilitychange", onVisibility);
    window.addEventListener("pagehide", flush);
    return () => {
      document.removeEventListener("visibilitychange", onVisibility);
      window.removeEventListener("pagehide", flush);
      flush();
    };
  }, []);

  const set = useCallback((next: SetStateAction<string>) => setValue(next), []);
  return [value, set] as const;
}
