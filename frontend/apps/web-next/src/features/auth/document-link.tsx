import type { ComponentProps } from "react";

/** Identity transitions must bypass the app router and start a new document. */
export function DocumentLink({ children, ...props }: ComponentProps<"a"> & { to?: string }) {
  delete props.to;
  return <a {...props}>{children}</a>;
}
