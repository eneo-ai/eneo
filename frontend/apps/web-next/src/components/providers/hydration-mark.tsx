"use client";

import { useEffect } from "react";

/**
 * Marks `<html data-hydrated>` once React has hydrated the page. The server's
 * HTML shows, and takes clicks, before the scripts attach their handlers; the
 * e2e fixture (tests/csp.ts) waits for the mark before a test acts on a page
 * it loaded. A click inside a part still hydrating is replayed by React.
 */
export function HydrationMark() {
  useEffect(() => {
    document.documentElement.dataset.hydrated = "";
  }, []);
  return null;
}
