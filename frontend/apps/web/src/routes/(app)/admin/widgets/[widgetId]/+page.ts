import { EneoError } from "@eneo/eneo-js";
import type { PageLoad } from "./$types";

export const load: PageLoad = async (event) => {
  event.depends("admin:widget-review");
  const { eneo } = await event.parent();
  try {
    const [review, policy] = await Promise.all([
      eneo.widgets.review({ id: event.params.widgetId }),
      eneo.widgets.policy.get()
    ]);
    return { review, policy };
  } catch (error) {
    // Deleted or another organisation's (404), or a mistyped id that is not a
    // UUID (422): the page says so in place.
    if (error instanceof EneoError && (error.status === 404 || error.status === 422)) {
      return { review: null, policy: null };
    }
    throw error;
  }
};
