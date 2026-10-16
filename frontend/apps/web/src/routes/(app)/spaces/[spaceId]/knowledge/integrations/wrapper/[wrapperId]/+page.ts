import { findIntegrationItems } from "$lib/features/integrations/integrationItems";

export const load = async (event) => {
  const { eneo, currentSpace } = await event.parent();
  const wrapperId = event.params.wrapperId;

  const wrapperItems = await findIntegrationItems(
    eneo,
    currentSpace,
    (item) => item.wrapper_id === wrapperId && item.space_id === currentSpace.id
  );

  const first = wrapperItems[0];
  const wrapperName =
    first && typeof first.wrapper_name === "string" && first.wrapper_name.trim().length > 0
      ? first.wrapper_name
      : (first?.name ?? "");

  return {
    wrapperId,
    wrapperName
  };
};
