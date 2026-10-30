import { useCallback, useEffect, useRef, useState, type SetStateAction } from "react";

const PREFIX = "eneo:chat-draft:";
/** Typing is written after this pause, and at once when the page is hidden. */
const WRITE_DELAY_MS = 300;

function read(key: string): string {
  try {
    return sessionStorage.getItem(PREFIX + key) ?? "";
  } catch {
    return "";
  }
}

function write(key: string, value: string) {
  try {
    if (value.trim()) sessionStorage.setItem(PREFIX + key, value);
    else sessionStorage.removeItem(PREFIX + key);
  } catch {
    // Storage blocked or full: the draft just lives in memory, as before.
  }
}

/**
 * The text typed in the composer, kept for the tab's life (sessionStorage:
 * gone with the tab and never shared, so a question typed on a shared screen
 * does not outlive it). A question typed and left (a tap on another
 * conversation, "Ny konversation", a reload, a phone that discarded the tab
 * while another app was open) is there again when the conversation is. `scope`
 * names the conversation: partner and session, or "new". Sending empties it.
 *
 * Files are not kept: they are uploaded, not typed.
 */
export function useChatDraft(scope: string) {
  const [value, setValue] = useState(() => read(scope));
  const latest = useRef({ scope, value });
  // Written once typing pauses, and when the page goes away or into the background.
  useEffect(() => {
    latest.current = { scope, value };
    const id = setTimeout(() => write(scope, value), WRITE_DELAY_MS);
    return () => clearTimeout(id);
  }, [scope, value]);
  useEffect(() => {
    const flush = () => write(latest.current.scope, latest.current.value);
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
