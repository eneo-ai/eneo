import Link from "@/lib/link";
import type { ComponentProps, MouseEvent } from "react";

/**
 * A link that switches the source page's tab or folder in place, without a
 * server round trip, and keeps a real address: a modified click, "open in new
 * tab" and copying the link still use `href`. Its address is this page's own,
 * so it is never prefetched: next/link takes `prefetch={false}`, Astryx's
 * Link and Button `as={SamePageLink}`.
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

/**
 * next/link without prefetching, for Astryx's `as`. Astryx passes the target
 * as both `href` and `to`; next/link would put `to` on the <a>.
 */
export function SamePageLink({
  children,
  ...props
}: ComponentProps<typeof Link> & { to?: unknown }) {
  delete props.to;
  return (
    <Link {...props} prefetch={false}>
      {children}
    </Link>
  );
}
