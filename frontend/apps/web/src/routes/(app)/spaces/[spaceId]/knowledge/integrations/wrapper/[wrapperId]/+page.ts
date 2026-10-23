import { error } from "@sveltejs/kit";
import { findIntegrationItems } from "$lib/features/integrations/integrationItems";

export const load = async (event) => {
  const { eneo, currentSpace } = await event.parent();
  const wrapperId = event.params.wrapperId;

  // The layout's space predates an import made since; such items are only on the server.
  const items = await findIntegrationItems(
    eneo,
    currentSpace,
    (item) => item.wrapper_id === wrapperId && item.space_id === currentSpace.id
  );
  if (items.length === 0) {
    throw error(404);
  }

  return { wrapperId, items };
};
