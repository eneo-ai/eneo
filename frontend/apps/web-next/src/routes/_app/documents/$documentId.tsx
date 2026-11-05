import { createFileRoute } from "@tanstack/react-router";
import { loadSourceDocument, SourceDocumentPage } from "@/features/knowledge/source-document";
import { browserApi } from "@/lib/api/browser";
import { routeTitle } from "@/lib/route-head";

export const Route = createFileRoute("/_app/documents/$documentId")({
  loader: ({ context: { queryClient }, params }) =>
    loadSourceDocument(queryClient, browserApi, params.documentId),
  head: routeTitle("document_lookup_title"),
  component: Page
});

function Page() {
  return <SourceDocumentPage document={Route.useLoaderData()} />;
}
