/**
 * The app's link: code outside src/app links through this module, never
 * through next/link. It is next/link now; the Vite build aliases this module
 * to the TanStack Router implementation, which is typed against `LinkProps`,
 * so the props hold only what both routers honour.
 */
import NextLink from "next/link";
import type { AnchorHTMLAttributes, ReactNode, Ref } from "react";

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

// next/link itself, typed down to the shared props. The default export keeps
// `import Link from "@/lib/link"` and `vi.mock` factories that return `default`.
const Link: (props: LinkProps) => ReactNode = NextLink;

export { Link, Link as default };
