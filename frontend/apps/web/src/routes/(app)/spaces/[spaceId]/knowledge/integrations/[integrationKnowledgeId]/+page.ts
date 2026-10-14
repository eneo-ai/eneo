import { error, redirect } from "@sveltejs/kit";
import type { IntegrationKnowledge } from "@eneo/eneo-js";
import { sourceHref } from "$lib/features/integrations/sources";

export const load = async (event) => {
  const { currentSpace } = await event.parent();
  const integrationKnowledgeId = event.params.integrationKnowledgeId;

  const items: IntegrationKnowledge[] =
    currentSpace.knowledge.integration_knowledge_list?.items ?? [];
  const knowledge = items.find(
    (item) => item.id === integrationKnowledgeId && item.space_id === currentSpace.id
  );
  if (!knowledge) {
    throw error(404);
  }

  const requestedTab = event.url.searchParams.get("tab");

  // An item imported with others lives on its wrapper's page, with its folder selected.
  if (knowledge.wrapper_id && knowledge.integration_type === "sharepoint") {
    throw redirect(
      307,
      sourceHref(
        event.params.spaceId,
        { kind: "wrapper", id: knowledge.wrapper_id },
        {
          folder: knowledge.id,
          tab: requestedTab === "skipped" || requestedTab === "problems" ? "problems" : undefined
        }
      )
    );
  }

  // Links from before the problems tab still name the skipped-files tab.
  if (requestedTab === "skipped") {
    throw redirect(307, `${event.url.pathname}?tab=problems`);
  }

  return { knowledgeId: knowledge.id };
};
