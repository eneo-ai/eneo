import { toastError } from "$lib/core/errors";
import { m } from "$lib/paraglide/messages";

/**
 * Copies text to the clipboard and exposes a short-lived `copied` flag for feedback.
 * A failure (no permission, insecure context) is reported with a toast.
 */
export function createCopyState(resetAfterMs = 2000) {
  let copied = $state(false);
  let timer: ReturnType<typeof setTimeout> | undefined;

  return {
    get copied() {
      return copied;
    },
    async copy(text: string): Promise<boolean> {
      try {
        await navigator.clipboard.writeText(text);
      } catch (error) {
        toastError(error, m.could_not_copy());
        return false;
      }
      copied = true;
      clearTimeout(timer);
      timer = setTimeout(() => (copied = false), resetAfterMs);
      return true;
    }
  };
}
