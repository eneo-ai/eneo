import { beforeNavigate, goto } from "$app/navigation";
import type { BeforeNavigate } from "@sveltejs/kit";
import { assignLocation } from "$lib/core/navigation";
import { m } from "$lib/paraglide/messages";
import type { Autosave } from "./widgetAutosave.svelte";

type AutosaveState = Pick<Autosave<object, object>, "unsaved" | "stranded" | "flush">;
type Destination = { url: URL; type: BeforeNavigate["type"]; delta: number; willUnload: boolean };

/** Hold client navigation until all queued edits have reached the server. */
export function guardAutosaveNavigation(autosave: AutosaveState): void {
  let saving = false;
  let destination: Destination | null = null;

  beforeNavigate((navigation) => {
    if (!autosave.unsaved) return;
    if (autosave.stranded) {
      if (!confirm(m.widget_admin_unsaved_leave_confirm())) navigation.cancel();
      return;
    }
    // Closing a tab has no destination to replay. The page's beforeunload
    // handler supplies the browser's native unsaved-changes prompt.
    if (!navigation.to) return;

    destination = {
      url: navigation.to.url,
      type: navigation.type,
      delta: navigation.type === "popstate" ? navigation.delta : 0,
      willUnload: navigation.willUnload
    };
    navigation.cancel();
    if (saving) return;
    saving = true;
    void autosave.flush().then(() => {
      saving = false;
      const next = destination;
      destination = null;
      // A failed or refused save leaves the editor and its edits in place.
      if (!next || autosave.unsaved) return;
      if (next.type === "popstate") {
        history.go(next.delta);
      } else if (next.willUnload) {
        assignLocation(next.url.href);
      } else {
        // The destination came from SvelteKit's already resolved navigation.
        // eslint-disable-next-line svelte/no-navigation-without-resolve
        void goto(next.url.href);
      }
    });
  });
}
