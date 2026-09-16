import { goto, preloadData } from "$app/navigation";
import { createContext } from "$lib/core/context";
import { localizeHref } from "$lib/paraglide/runtime";
import { visibleEntries } from "@eneo/whats-new";
import type { Locale, Release } from "@eneo/whats-new";
import { writable } from "svelte/store";
import { spotlight, type SpotlightLabels, type SpotlightStep } from "./spotlight";

/** The release entries own the walkthrough's content and order. */
export function tourSteps(release: Release, isAdmin: boolean, locale: Locale): SpotlightStep[] {
  return visibleEntries(release, isAdmin).flatMap((entry) =>
    entry.showMe
      ? [{ ...entry.showMe, title: entry.title[locale], description: entry.body[locale] }]
      : []
  );
}

export type TourOutcome = "completed" | "cancelled" | "unavailable";

const [getWhatsNewTour, setWhatsNewTour] =
  createContext<ReturnType<typeof createWhatsNewTour>>("What's new walkthrough");
export { getWhatsNewTour };

export function initWhatsNewTour() {
  const tour = createWhatsNewTour();
  setWhatsNewTour(tour);
  return tour;
}

/** One walkthrough per app layout, shared by Show me and the announcement. */
export function createWhatsNewTour() {
  const running = writable(false);
  let active: { controller: AbortController; expectedHref: string | null } | null = null;

  function stop() {
    active?.controller.abort();
  }

  /** Called by the app layout's beforeNavigate hook, including browser back. */
  function beforeNavigation(destination: URL | null) {
    if (!active) return;
    if (active.expectedHref && destination?.href === active.expectedHref) {
      active.expectedHref = null;
      return;
    }
    stop();
  }

  async function start(candidates: SpotlightStep[], labels: SpotlightLabels): Promise<TourOutcome> {
    stop();
    const session = { controller: new AbortController(), expectedHref: null as string | null };
    active = session;
    running.set(true);
    const { signal } = session.controller;
    const escape = (event: KeyboardEvent) => {
      if (event.key === "Escape") session.controller.abort();
    };
    window.addEventListener("keydown", escape);

    // Only inspect the next page. SvelteKit caches one preload at a time;
    // immediately navigating to it reuses that load's permission checks/data.
    const steps = [...candidates];
    let index = 0;
    let direction: 1 | -1 = 1;
    let shown = false;
    try {
      while (index >= 0 && index < steps.length) {
        signal.throwIfAborted();
        const step = steps[index];
        const href = localizeHref(step.href);
        const result = await untilAborted(
          preloadData(href).catch(() => null),
          signal
        );
        if (!result || result.type !== "loaded" || result.status !== 200) {
          steps.splice(index, 1);
          if (direction === -1) index--;
          continue;
        }

        signal.throwIfAborted();
        session.expectedHref = new URL(href, window.location.href).href;
        // eslint-disable-next-line svelte/no-navigation-without-resolve -- localizeHref handles routing
        await untilAborted(goto(href), signal);
        session.expectedHref = null;
        signal.throwIfAborted();

        const outcome = await untilAborted(
          spotlight(step, {
            labels,
            signal,
            // The total counts stops not yet found unreachable; later pages
            // are checked on arrival, so it can shrink mid-walkthrough.
            progress: candidates.length > 1 ? { index, total: steps.length } : undefined
          }),
          signal
        );
        if (outcome === "closed") return "cancelled";
        if (outcome === "no-anchor") {
          steps.splice(index, 1);
          if (direction === -1) index--;
          continue;
        }
        shown = true;
        direction = outcome === "previous" ? -1 : 1;
        index += direction;
      }
      return shown ? "completed" : "unavailable";
    } catch (error) {
      if (signal.aborted) return "cancelled";
      throw error;
    } finally {
      session.controller.abort();
      window.removeEventListener("keydown", escape);
      if (active === session) {
        active = null;
        running.set(false);
      }
    }
  }

  return { start, stop, beforeNavigation, running: { subscribe: running.subscribe } };
}

/** SvelteKit cannot abort a preload; stop waiting and ignore its late result. */
function untilAborted<T>(work: Promise<T>, signal: AbortSignal): Promise<T> {
  return new Promise((resolve, reject) => {
    const abort = () => reject(signal.reason);
    signal.addEventListener("abort", abort, { once: true });
    work.then(resolve, reject).finally(() => signal.removeEventListener("abort", abort));
    if (signal.aborted) abort();
  });
}
