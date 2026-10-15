import type { MouseEvent } from "react";

/**
 * A link that switches the source page's tab or folder in place, without a
 * server round trip, and keeps a real address: a modified click, "open in new
 * tab" and copying the link still use `href`.
 */
export type InPlaceLink = { href: string; onClick: (event: MouseEvent) => void };

export function inPlaceLink(href: string, go: () => void): InPlaceLink {
  return {
    href,
    onClick: (event) => {
      if (event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) {
        return;
      }
      // next/link (and Astryx links through it) skip their navigation for a prevented click.
      event.preventDefault();
      go();
    }
  };
}
