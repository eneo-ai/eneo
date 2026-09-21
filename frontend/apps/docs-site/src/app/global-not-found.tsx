import DocsShell from "@/components/DocsShell";

import NotFound from "./[[...mdxPath]]/not-found";

export { metadata } from "@/components/DocsShell";

// Unmatched URLs have no language segment to trust, so the 404 is English.
export default function GlobalNotFound() {
  return (
    <DocsShell language="en" page="/">
      <NotFound />
    </DocsShell>
  );
}
