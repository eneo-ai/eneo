import { error, redirect } from "@sveltejs/kit";
import { findIntegrationItems } from "$lib/features/integrations/integrationItems";
import { sourceHref, type SourceTab } from "$lib/features/integrations/sources";

/** The wrapper page's tab for a tab of the item page; an old `skipped` link opens Problems. */
function wrapperTab(tab: string | null): SourceTab | undefined {
  if (tab === "skipped" || tab === "problems") return "problems";
  if (tab === "activity" || tab === "content") return tab;
  return undefined;
}

export const load = async (event) => {
  const { eneo, currentSpace } = await event.parent();
  const integrationKnowledgeId = event.params.integrationKnowledgeId;

  // The layout's space predates an import made since; such an item is only on the server.
  const [knowledge] = await findIntegrationItems(
    eneo,
    currentSpace,
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
        { folder: knowledge.id, tab: wrapperTab(requestedTab) }
      )
    );
  }

  // Links from before the problems tab still name the skipped-files tab.
  if (requestedTab === "skipped") {
    throw redirect(307, `${event.url.pathname}?tab=problems`);
  }

  return { knowledge };
};
