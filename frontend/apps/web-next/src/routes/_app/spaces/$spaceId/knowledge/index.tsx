import { createFileRoute } from "@tanstack/react-router";
import { KnowledgePage } from "@/features/knowledge/knowledge-page";
import { spaceTitle } from "@/lib/route-head";
import { runtimeConfig } from "@/lib/runtime-config";

export const Route = createFileRoute("/_app/spaces/$spaceId/knowledge/")({
  head: ({ matches, match }) => spaceTitle(matches, match.context.t, match.context.t("knowledge")),
  remountDeps: ({ params }) => params.spaceId,
  component: KnowledgeHub
});

function KnowledgeHub() {
  return (
    <KnowledgePage
      integrationRequestFormUrl={runtimeConfig().request_integration_form_url ?? undefined}
    />
  );
}
