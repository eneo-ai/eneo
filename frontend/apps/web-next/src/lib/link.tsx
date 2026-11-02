/**
 * App links on TanStack Router, with one shared contract for feature components.
 *
 * An app path navigates in the app; it is the current page (`aria-current`)
 * only when path and query both match, so one link per page is current. An
 * `aria-current` the caller passes, even `undefined`, wins over that.
 * Another site, a `#hash` and a download are plain anchors.
 */
import { useLinkProps, type AnyRouter } from "@tanstack/react-router";
import type { AnchorHTMLAttributes, ForwardedRef, ReactNode, Ref } from "react";
export type LinkProps = Omit<AnchorHTMLAttributes<HTMLAnchorElement>, "href"> & {
  /** An absolute app path (`/x?tab=y#z`), a `#hash`, or an external URL; never relative. */
  href: string;
  /** `false`: never load the target ahead of a click. */
  prefetch?: boolean;
  /** `false` keeps the scroll position; by default the page scrolls to the top. */
  scroll?: boolean;
  /** Replaces the current history entry instead of adding one. */
  replace?: boolean;
  ref?: Ref<HTMLAnchorElement>;
};

import { scrollOptions } from "./navigation";
import { parseSearch } from "./router/search";

// A scheme (`https:`, `mailto:`), or a host without one (`//host`, which
// browsers also read with backslashes).
const OTHER_SITE = /^(?:[a-z][a-z0-9+.-]*:|[\\/]{2})/i;

function AppLink({ href, prefetch, scroll, replace, ref, children, ...anchor }: LinkProps) {
  const url = new URL(href, "http://n");
  const props = useLinkProps<AnyRouter, string, string>(
    {
      ...anchor,
      to: url.pathname,
      search: parseSearch(url.search),
      hash: url.hash.slice(1),
      preload: prefetch === false ? false : undefined,
      ...scrollOptions(scroll),
      replace,
      activeOptions: { exact: true, includeSearch: true }
    },
    // The ref reaches the <a> below; TanStack types it for any element.
    ref as ForwardedRef<Element>
  );
  const current = "aria-current" in anchor ? anchor["aria-current"] : props["aria-current"];
  return (
    <a {...props} aria-current={current}>
      {children}
    </a>
  );
}

const Link: (props: LinkProps) => ReactNode = ({
  href,
  prefetch,
  scroll,
  replace,
  ref,
  children,
  ...anchor
}) =>
  // The browser handles another site, a #hash and a download.
  OTHER_SITE.test(href) || href.startsWith("#") || (anchor.download ?? false) !== false ? (
    <a {...anchor} href={href} ref={ref}>
      {children}
    </a>
  ) : (
    <AppLink
      {...anchor}
      href={href}
      prefetch={prefetch}
      scroll={scroll}
      replace={replace}
      ref={ref}
    >
      {children}
    </AppLink>
  );

export { Link, Link as default };
