import { error } from "@sveltejs/kit";

export const load = async (event) => {
  const { currentSpace } = await event.parent();
  const wrapperId = event.params.wrapperId;

  const items: { wrapper_id?: string | null; space_id: string }[] =
    currentSpace.knowledge.integration_knowledge_list?.items ?? [];
  if (!items.some((item) => item.wrapper_id === wrapperId && item.space_id === currentSpace.id)) {
    throw error(404);
  }

  return { wrapperId };
};
