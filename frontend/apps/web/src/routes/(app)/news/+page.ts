import { redirect } from "@sveltejs/kit";

// The organisation can turn the feature off; the page then does not exist
// for its users (menu entry, dot and announcement are hidden as well).
export const load = async (event) => {
  const { settings } = await event.parent();
  if (settings.whats_new_enabled === false) {
    redirect(302, "/");
  }
  return {};
};
