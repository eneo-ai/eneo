"use client";

import { useCallback, useEffect, useRef } from "react";

const CLEAR_AFTER_MS = 4_000;

/**
 * The chat's single polite live region (ACCESSIBILITY.md → AI chat). It is
 * mounted empty and only receives short status messages ("Svaret är klart",
 * errors, tool approvals) written from event handlers; streaming text never
 * goes here. Messages are written imperatively so announcing never re-renders
 * the conversation, and cleared shortly after so stale text does not linger.
 */
export function useLiveRegion() {
  const regionRef = useRef<HTMLDivElement>(null);
  const clearTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(
    () => () => {
      if (clearTimer.current) clearTimeout(clearTimer.current);
    },
    []
  );

  const announce = useCallback((message: string) => {
    const region = regionRef.current;
    if (!region || !message) return;
    if (clearTimer.current) clearTimeout(clearTimer.current);
    // Re-announce identical consecutive messages: clear first, write next tick.
    region.textContent = "";
    setTimeout(() => {
      region.textContent = message;
      clearTimer.current = setTimeout(() => {
        region.textContent = "";
      }, CLEAR_AFTER_MS);
    }, 50);
  }, []);

  return { regionRef, announce };
}

export function LiveRegion({ regionRef }: { regionRef: React.RefObject<HTMLDivElement | null> }) {
  return (
    <div
      ref={regionRef}
      role="status"
      aria-live="polite"
      aria-atomic="true"
      className="sr-only"
      data-testid="chat-live-region"
    />
  );
}
