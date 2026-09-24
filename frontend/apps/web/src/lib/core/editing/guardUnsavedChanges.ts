import { beforeNavigate } from "$app/navigation";
import { get, type Readable } from "svelte/store";
import { m } from "$lib/paraglide/messages";

/**
 * Asks for confirmation before leaving a page with unsaved editor changes. Changes are discarded on
 * every leave, so attachments that were uploaded but never saved get deleted.
 * Must be called during component initialisation.
 */
export function guardUnsavedChanges(editor: {
  state: { currentChanges: Readable<{ hasUnsavedChanges: boolean }> };
  discardChanges: () => void;
}) {
  beforeNavigate((navigation) => {
    if (
      get(editor.state.currentChanges).hasUnsavedChanges &&
      !confirm(m.unsaved_changes_warning())
    ) {
      navigation.cancel();
      return;
    }
    editor.discardChanges();
  });
}
