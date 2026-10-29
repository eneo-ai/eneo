import { EneoError } from "@eneo/eneo-js";
import type { PageLoad } from "./$types";

/**
 * Resolves a document reference copied from a widget answer. Anyone who may
 * read the document sees it; everyone else gets a page that says whom to ask,
 * without confirming whether the document exists.
 */
export const load: PageLoad = async (event) => {
  const { eneo } = await event.parent();
  const id = event.params.id;
  try {
    const blob = await eneo.infoBlobs.get({ id });
    const group = blob.group_id
      ? await eneo.groups.get({ id: blob.group_id }).catch(() => null)
      : null;
    const website = blob.website_id
      ? await eneo.websites.get({ id: blob.website_id }).catch(() => null)
      : null;
    const spaceId = group?.space_id ?? website?.space_id ?? null;
    const space = spaceId ? await eneo.spaces.get({ id: spaceId }).catch(() => null) : null;
    return { id, blob, group, website, space };
  } catch (error) {
    if (error instanceof EneoError && [403, 404, 422].includes(error.status)) {
      return { id, blob: null, group: null, website: null, space: null };
    }
    throw error;
  }
};
