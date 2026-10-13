import { error } from "@sveltejs/kit";
import type { IntegrationKnowledge } from "@eneo/eneo-js";
import {
  DEFAULT_INTEGRATION_DOCUMENTS_QUERY,
  type IntegrationDocumentsPage,
  type IntegrationDocumentsTab,
  type IntegrationSkippedDocuments
} from "$lib/features/integrations/integrationDocuments";

export const load = async (event) => {
  const { eneo, currentSpace } = await event.parent();
  const integrationKnowledgeId = event.params.integrationKnowledgeId;

  const items: IntegrationKnowledge[] =
    currentSpace.knowledge.integration_knowledge_list?.items ?? [];
  const knowledge = items.find(
    (item) => item.id === integrationKnowledgeId && item.space_id === currentSpace.id
  );
  if (!knowledge) {
    throw error(404);
  }

  const [documents, skipped] = await Promise.all([
    eneo.integrations.knowledge.listDocuments({
      knowledge,
      space: currentSpace,
      ...DEFAULT_INTEGRATION_DOCUMENTS_QUERY
    }) as Promise<IntegrationDocumentsPage>,
    (
      eneo.integrations.knowledge.listSkippedDocuments({
        knowledge,
        space: currentSpace
      }) as Promise<IntegrationSkippedDocuments>
    ).catch((err: unknown) => {
      console.error("Could not load the skipped files of an integration item", err);
      return null;
    })
  ]);

  const initialTab: IntegrationDocumentsTab =
    event.url.searchParams.get("tab") === "skipped" ? "skipped" : "documents";

  return { knowledge, documents, skipped, initialTab };
};
