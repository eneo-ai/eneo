/**
 * The app's link (`@/lib/link`) on TanStack Router: the Vite build aliases the
 * seam to this module (vite.config.mts), typed against the Next one's props.
 *
 * An app path navigates in the app; it is the current page (`aria-current`)
 * only when path and query both match, so one link per page is current. An
 * `aria-current` the caller passes, even `undefined`, wins over that.
 * Another site, a `#hash` and a download are plain anchors.
 */
import { useLinkProps, type AnyRouter } from "@tanstack/react-router";
import type { ForwardedRef, ReactNode } from "react";
import type { LinkProps } from "./link";
import { scrollOptions } from "./navigation.tanstack";
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
  // The browser handles another site, a #hash and a download (as next/link).
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
