import { getEneo } from "$lib/core/Eneo";
import { m } from "$lib/paraglide/messages";

/**
 * Upload/delete state for an `IconUpload`. The id is always read through `iconId`, so the shown icon
 * follows whichever state owns it; `setIconId` persists (or stages) a changed id.
 * Must be called during component initialisation.
 */
export function createIconEditor(options: {
  iconId: () => string | null | undefined;
  setIconId: (id: string | null) => unknown;
}) {
  const eneo = getEneo();
  let uploading = $state(false);
  let error = $state<string | null>(null);

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
      try {
        const icon = await eneo.icons.upload({ file });
        await options.setIconId(icon.id);
      } catch (e) {
        console.error("Failed to upload icon:", e);
        error = m.avatar_upload_failed();
      } finally {
        uploading = false;
      }
    },
    async remove() {
      error = null;
      try {
        const id = options.iconId();
        if (id) await eneo.icons.delete({ id });
        await options.setIconId(null);
      } catch (e) {
        console.error("Failed to delete icon:", e);
        error = m.avatar_delete_failed();
      }
    }
  };
}
