import DocsShell from "@/components/DocsShell";

import NotFound from "./[[...mdxPath]]/not-found";

export { metadata } from "@/components/DocsShell";

// The document is exported in English; NotFound switches to the address's
// language on the client.
export default function GlobalNotFound() {
  return (
    <DocsShell language="en" page="/">
      <NotFound />
    </DocsShell>
  );
}
