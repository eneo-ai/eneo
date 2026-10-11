// Bits UI releases the body scroll lock of an unmounted dialog, sheet or menu
// from a timer (24 ms by default, body-scroll-lock.svelte.js) and keeps
// `overflow: hidden` on the body until it has run. jsdom is gone once a test
// file has ended, so a release that is still pending then throws "document is
// not defined" as an unhandled error: the run fails although every test passed.

// Taken before a test can install fake timers, so the wait runs on real time.
const realSetTimeout = globalThis.setTimeout;
const POLL_MS = 4;
// Bound for a file whose lock is not released on real time: a component that
// is still mounted holds it, or the release was scheduled on a fake clock.
// Counted in turns, not in elapsed time, so a stalled worker cannot use it up
// before the release timer has had its turn.
const MAX_POLLS = 60;

/** Wait until the scroll lock of the file's last unmounted component is released. */
export async function settleBodyScrollLock(): Promise<void> {
  for (let poll = 0; poll < MAX_POLLS && document.body.style.overflow === "hidden"; poll += 1) {
    await new Promise((resolve) => realSetTimeout(resolve, POLL_MS));
  }
}
