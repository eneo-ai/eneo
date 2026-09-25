import { EneoError } from "@eneo/eneo-js";
import { error } from "@sveltejs/kit";
import { m } from "$lib/paraglide/messages";
import type { PageLoad } from "./$types";

export const load: PageLoad = async (event) => {
  event.depends("admin:space");
  const { eneo } = await event.parent();
  const [space, security] = await Promise.all([
    eneo.spaces.admin.get({ id: event.params.spaceId }).catch((reason: unknown) => {
      if (reason instanceof EneoError && reason.status === 404) {
        // Deleted, personal, the organisation space or another tenant's: the page says so.
        return null;
      }
      if (reason instanceof EneoError && reason.status === 403) {
        error(403, { status: 403, code: 0, message: m.admin_spaces_forbidden() });
      }
      throw reason;
    }),
    eneo.securityClassifications.list().catch(() => null)
  ]);
  return { space, securityEnabled: security?.security_enabled ?? false };
};
