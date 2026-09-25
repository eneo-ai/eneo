import { tick } from "svelte";

type Options = {
  close: () => void;
  /** Loads the page's new state, e.g. `invalidate(...)`. */
  reload: () => Promise<unknown>;
  /** Where focus goes once the page shows the new state; the opener may be gone by then. */
  focusAfter: () => HTMLElement | null | undefined;
};

/**
 * Closing a dialog whose action moved the page on: the dialog closes, the
 * page reloads, and focus lands on `focusAfter` instead of the opener.
 * Wire `onCloseAutoFocus` to the dialog content and call `reset` when it
 * opens, so a plain close still hands focus back as usual.
 */
export function settleDialog({ close, reload, focusAfter }: Options) {
  let settling = false;
  let closed: () => void = () => {};

  return {
    reset() {
      settling = false;
    },
    async settle() {
      settling = true;
      const dialogClosed = new Promise<void>((resolve) => (closed = resolve));
      close();
      // The close hands focus back through onCloseAutoFocus; if that never
      // comes, the page must not wait for it.
      const timeout = new Promise<void>((resolve) => setTimeout(resolve, 1000));
      await Promise.all([reload(), Promise.race([dialogClosed, timeout])]);
      await tick();
      focusAfter()?.focus();
    },
    onCloseAutoFocus(event: Event) {
      if (!settling) return;
      event.preventDefault();
      closed();
    }
  };
}
