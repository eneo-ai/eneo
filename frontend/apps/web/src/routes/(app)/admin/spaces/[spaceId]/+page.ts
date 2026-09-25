import { EneoError } from "@eneo/eneo-js";
import { error } from "@sveltejs/kit";
import { m } from "$lib/paraglide/messages";
import type { PageLoad } from "./$types";

export const load: PageLoad = async (event) => {
  event.depends("admin:space");
  const { eneo } = await event.parent();
  const [space, security] = await Promise.all([
    eneo.spaces.admin.get({ id: event.params.spaceId }).catch((reason: unknown) => {
      // Deleted, personal, the organisation space or another tenant's (404), or a
      // mistyped id that is not a UUID (422): the page says the space is not there.
      if (reason instanceof EneoError && (reason.status === 404 || reason.status === 422)) {
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
