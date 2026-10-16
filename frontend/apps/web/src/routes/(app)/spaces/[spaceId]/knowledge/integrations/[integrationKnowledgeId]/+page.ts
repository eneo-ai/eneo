import { error } from "@sveltejs/kit";
import { getErrorMessage } from "$lib/core/errors";
import {
  DEFAULT_INTEGRATION_DOCUMENTS_QUERY,
  emptyDocumentsPage,
  type IntegrationDocumentsTab
} from "$lib/features/integrations/integrationDocuments";
import { findIntegrationItems } from "$lib/features/integrations/integrationItems";

export const load = async (event) => {
  const { eneo, currentSpace } = await event.parent();
  const integrationKnowledgeId = event.params.integrationKnowledgeId;

  const [knowledge] = await findIntegrationItems(
    eneo,
    currentSpace,
    (item) => item.id === integrationKnowledgeId && item.space_id === currentSpace.id
  );
  if (!knowledge) {
    throw error(404);
  }

  // A failed list keeps the page: the view shows the error in place, with a retry.
  let documentsError: string | null = null;
  const [documents, skipped] = await Promise.all([
    eneo.integrations.knowledge
      .listDocuments({
        knowledge,
        space: currentSpace,
        ...DEFAULT_INTEGRATION_DOCUMENTS_QUERY
      })
      .catch((err: unknown) => {
        documentsError = getErrorMessage(err);
        return emptyDocumentsPage();
      }),
    eneo.integrations.knowledge
      .listSkippedDocuments({ knowledge, space: currentSpace })
      .catch((err: unknown) => {
        console.error("Could not load the skipped files of an integration item", err);
        return null;
      })
  ]);

  const initialTab: IntegrationDocumentsTab =
    event.url.searchParams.get("tab") === "skipped" ? "skipped" : "documents";

  return { knowledge, documents, documentsError, skipped, initialTab };
};
