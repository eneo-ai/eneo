import { getEneo } from "$lib/core/Eneo";
import { m } from "$lib/paraglide/messages";

/**
 * Upload/delete state for an `IconUpload`. The id is always read through `iconId`, so the shown icon
 * follows whichever state owns it; `setIconId` persists a changed id, or only stages it when `staged`.
 * Must be called during component initialisation.
 */
export function createIconEditor(options: {
  iconId: () => string | null | undefined;
  setIconId: (id: string | null) => unknown;
  staged?: boolean;
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
      const id = options.iconId();
      try {
        await options.setIconId(null);
      } catch (e) {
        console.error("Failed to delete icon:", e);
        error = m.avatar_delete_failed();
        return;
      }
      // The server only deletes an icon no resource shows any more, so this follows the persisted
      // removal and is cleanup: an icon another resource still shows is kept.
      if (id && !options.staged) await eneo.icons.delete({ id }).catch(() => {});
    }
  };
}
