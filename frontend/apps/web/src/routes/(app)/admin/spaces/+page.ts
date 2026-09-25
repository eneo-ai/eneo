import { EneoError } from "@eneo/eneo-js";
import { error } from "@sveltejs/kit";
import { m } from "$lib/paraglide/messages";
import type { PageLoad } from "./$types";

export const load: PageLoad = async (event) => {
  event.depends("admin:spaces");
  const { eneo } = await event.parent();
  const [list, security] = await Promise.all([
    eneo.spaces.admin.list().catch((reason: unknown) => {
      if (reason instanceof EneoError && reason.status === 403) {
        error(403, { status: 403, code: 0, message: m.admin_spaces_forbidden() });
      }
      // Any other failure is shown on the page with a way to try again.
      console.error("Failed to load the spaces", reason);
      return null;
    }),
    // Without the setting the classification column is left out, not the list.
    eneo.securityClassifications.list().catch(() => null)
  ]);
  return { list, securityEnabled: security?.security_enabled ?? false };
};
