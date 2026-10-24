"use client";

import { useAnnounce } from "@astryxdesign/core/hooks";
import { useEffect, useRef } from "react";

/**
 * Announces `message` politely when it appears or changes while the page is
 * open; not on arrival, and not when the same message is shown again. For a
 * notice that is not a live region itself (Astryx's error Banner is an
 * assertive alert), so switching back to it never reads it out again.
 */
export function useAnnounceChange(message: string | null) {
  const announce = useAnnounce();
  const last = useRef(message);
  useEffect(() => {
    if (message !== null && message !== last.current) announce(message);
    last.current = message;
  }, [announce, message]);
}
