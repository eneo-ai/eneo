import { getEneo } from "$lib/core/Eneo";
import { m } from "$lib/paraglide/messages";

/**
 * Upload/delete state for an `IconUpload`. The id is always read through `iconId`, so the shown icon
 * follows whichever state owns it. `setIconId` persists a changed id, and the server deletes the icon it
 * replaced. When `setIconId` only stages the id, pass `savedIconId`: an upload that is replaced or
 * removed before it is saved is then deleted here, because no save will ever release it.
 * Must be called during component initialisation.
 */
export function createIconEditor(options: {
  iconId: () => string | null | undefined;
  setIconId: (id: string | null) => unknown;
  savedIconId?: () => string | null | undefined;
}) {
  const eneo = getEneo();
  let uploading = $state(false);
  let error = $state<string | null>(null);

  async function dropUnsaved(id: string | null | undefined) {
    if (!options.savedIconId || !id || id === options.savedIconId()) return;
    await eneo.icons.delete({ id }).catch(() => {});
  }

  return {
    get url() {
      const id = options.iconId();
      return id ? eneo.icons.url({ id }) : null;
    },
    get uploading() {
      return uploading;
    },
    get error() {
      return error;
    },
    async upload(file: File) {
      uploading = true;
      error = null;
      const replaced = options.iconId();
      let uploaded: string | undefined;
      try {
        uploaded = (await eneo.icons.upload({ file })).id;
        await options.setIconId(uploaded);
      } catch (e) {
        console.error("Failed to upload icon:", e);
        error = m.avatar_upload_failed();
        // Nothing shows an upload whose id could not be set, and nothing else would delete it.
        if (uploaded) await eneo.icons.delete({ id: uploaded }).catch(() => {});
        return;
      } finally {
        uploading = false;
      }
      await dropUnsaved(replaced);
    },
    async remove() {
      error = null;
      const id = options.iconId();
      try {
        await options.setIconId(null);
      } catch (e) {
        console.error("Failed to delete icon:", e);
        error = m.avatar_delete_failed();
        return;
      }
      await dropUnsaved(id);
    }
  };
}
