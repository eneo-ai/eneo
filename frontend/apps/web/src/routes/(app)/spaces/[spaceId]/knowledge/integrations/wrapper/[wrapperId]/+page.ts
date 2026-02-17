export const load = async (event) => {
  const { currentSpace } = await event.parent();
  const wrapperId = event.params.wrapperId;

  const allIntegrations = currentSpace.knowledge.integration_knowledge_list?.items ?? [];
  const wrapperItems = allIntegrations.filter(
    (k: { wrapper_id?: string | null; space_id: string }) =>
      k.wrapper_id === wrapperId && k.space_id === currentSpace.id
  );

  const first = wrapperItems[0];
  const wrapperName =
    first && typeof first.wrapper_name === "string" && first.wrapper_name.trim().length > 0
      ? first.wrapper_name
      : first?.name ?? "";

  return {
    wrapperId,
    wrapperName
  };
};
