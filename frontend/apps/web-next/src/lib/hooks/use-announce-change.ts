"use client";

import { useAnnounce } from "@astryxdesign/core/hooks";
import { useEffect, useRef } from "react";

/**
 * Announces `message` politely when it appears or changes while the page is
 * open; not on arrival, and not when the same message is shown again. For a
 * notice that is not a live region itself (Astryx's error Banner is an
 * assertive alert), so switching back to it never reads it out again.
 * `key` is what counts as a change, when the words alone would mislead: a
 * switch of language changes every message without changing the state.
 */
export function useAnnounceChange(message: string | null, key: unknown = message) {
  const announce = useAnnounce();
  const last = useRef(key);
  useEffect(() => {
    if (message !== null && key !== last.current) announce(message);
    last.current = key;
  }, [announce, message, key]);
}
