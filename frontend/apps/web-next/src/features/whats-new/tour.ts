import { driver } from "driver.js";
import type { Locale, ReleaseEntry } from "@eneo/whats-new";

export type TourOutcome = "completed" | "cancelled" | "unavailable";
type SpotlightOutcome = "next" | "previous" | "closed" | "no-anchor";

export interface TourLabels {
  done: string;
  next: string;
  previous: string;
  progress: string;
  version: string;
}

/** A single stop is prechecked and navigated to before its anchor is highlighted. */
export async function runTour(
  candidates: ReleaseEntry[],
  locale: Locale,
  labels: TourLabels,
  navigate: (href: string) => void,
  signal: AbortSignal
): Promise<TourOutcome> {
  const steps = candidates.filter((entry) => entry.showMe);
  let index = 0;
  let direction: 1 | -1 = 1;
  let shown = false;

  try {
    while (index >= 0 && index < steps.length) {
      signal.throwIfAborted();
      const step = steps[index];
      if (!step?.showMe) break;
      // The React governance screen combines the Svelte configuration tab into one page.
      const href =
        step.showMe.href === "/admin/personal-assistant/configuration"
          ? "/admin/personal-assistant"
          : step.showMe.href;

      // A denied or missing page must not interrupt the rest of the tour.
      const response = await fetch(href, { redirect: "manual", signal }).catch(() => null);
      if (!response || !response.ok) {
        steps.splice(index, 1);
        if (direction === -1) index--;
        continue;
      }

      signal.throwIfAborted();
      navigate(href);
      const element = await waitForAnchor(href, step.showMe.anchor, signal);
      const outcome = element
        ? await spotlight(element, step, locale, labels, { index, total: steps.length }, signal)
        : "no-anchor";
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
  }
}

/** Next navigation is asynchronous; observe only the intended route and anchor. */
function waitForAnchor(
  href: string,
  anchor: string,
  signal: AbortSignal
): Promise<HTMLElement | null> {
  return new Promise((resolve) => {
    const targetPath = new URL(href, window.location.href).pathname;
    let finished = false;
    const finish = (element: HTMLElement | null) => {
      if (finished) return;
      finished = true;
      observer.disconnect();
      clearTimeout(timeout);
      signal.removeEventListener("abort", abort);
      resolve(element);
    };
    const check = () => {
      if (window.location.pathname !== targetPath) return;
      const element = document.querySelector<HTMLElement>(`[data-tour="${anchor}"]`);
      if (element) finish(element);
    };
    const abort = () => finish(null);
    const observer = new MutationObserver(check);
    const timeout = setTimeout(() => finish(null), 2500);
    signal.addEventListener("abort", abort, { once: true });
    observer.observe(document.body, {
      childList: true,
      subtree: true,
      attributes: true,
      attributeFilter: ["data-tour"]
    });
    if (signal.aborted) abort();
    else check();
  });
}

function spotlight(
  element: HTMLElement,
  entry: ReleaseEntry,
  locale: Locale,
  labels: TourLabels,
  progress: { index: number; total: number },
  signal: AbortSignal
): Promise<SpotlightOutcome> {
  return new Promise((resolve, reject) => {
    let finished = false;
    const isFirst = progress.index === 0;
    const isLast = progress.index === progress.total - 1;
    const finish = (outcome: SpotlightOutcome) => {
      if (finished) return;
      finished = true;
      signal.removeEventListener("abort", abort);
      window.removeEventListener("keyup", navigate);
      tour.destroy();
      if (!signal.aborted && element.isConnected) {
        const focusTarget =
          element.querySelector<HTMLElement>(
            'button, a[href], input, select, textarea, [tabindex]:not([tabindex="-1"])'
          ) ?? element;
        if (focusTarget === element && !element.hasAttribute("tabindex")) element.tabIndex = -1;
        focusTarget.focus({ preventScroll: true });
      }
      resolve(outcome);
    };
    const abort = () => finish("closed");
    const navigate = (event: KeyboardEvent) => {
      if (event.key === "ArrowRight") finish("next");
      else if (event.key === "ArrowLeft" && !isFirst) finish("previous");
    };
    const tour = driver({
      animate: true,
      allowKeyboardControl: false,
      overlayOpacity: 0.55,
      stagePadding: 8,
      stageRadius: 8,
      showButtons: progress.total > 1 ? ["previous", "next", "close"] : ["next", "close"],
      disableButtons: isFirst ? ["previous"] : [],
      showProgress: progress.total > 1,
      progressText: labels.progress,
      nextBtnText: labels.next,
      prevBtnText: labels.previous,
      doneBtnText: isLast ? labels.done : labels.next,
      popoverClass: "eneo-spotlight",
      steps: [
        {
          element,
          popover: {
            title: entry.title[locale] ?? entry.title.en,
            description: entry.body[locale] ?? entry.body.en
          }
        }
      ],
      onPopoverRender: (popover) => {
        const badge = document.createElement("span");
        badge.className = "eneo-spotlight-version";
        badge.textContent = labels.version;
        popover.title.before(badge);
        if (progress.total > 1) {
          popover.progress.textContent = labels.progress
            .replace("{current}", String(progress.index + 1))
            .replace("{total}", String(progress.total));
          if (!isFirst) {
            popover.previousButton.disabled = false;
            popover.previousButton.classList.remove("driver-popover-btn-disabled");
          }
        }
        queueMicrotask(() => {
          if (!signal.aborted && popover.wrapper.isConnected) popover.nextButton.focus();
        });
      },
      onNextClick: () => finish("next"),
      onPrevClick: () => {
        if (!isFirst) finish("previous");
      },
      onDestroyStarted: () => finish("closed")
    });
    signal.addEventListener("abort", abort, { once: true });
    window.addEventListener("keyup", navigate);
    try {
      element.scrollIntoView({ block: "center", behavior: "smooth" });
      tour.drive();
    } catch (error) {
      reject(error);
      finish("closed");
    }
  });
}
