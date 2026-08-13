import { createEneo } from "@eneo/eneo-js";
import { fail } from "@sveltejs/kit";
import type { Actions } from "./$types";

export const actions: Actions = {
  probe: async ({ request, locals, fetch }) => {
    const form = await request.formData();
    const websiteId = form.get("website_id");
    if (typeof websiteId !== "string" || !websiteId) {
      return fail(400, { probeFailed: true });
    }

    if (!locals.id_token || !locals.environment.baseUrl) {
      return fail(401, { probeFailed: true });
    }

    try {
      const eneo = createEneo({
        baseUrl: locals.environment.baseUrl,
        token: locals.id_token,
        fetch
      });
      return {
        probeResult: await eneo.crawler.probe(websiteId),
        websiteId
      };
    } catch {
      return fail(502, { probeFailed: true, websiteId });
    }
  }
};
