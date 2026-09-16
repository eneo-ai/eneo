import type { ShowMe } from "@eneo/whats-new";

const ANCHOR_WAIT_MS = 2500;

export interface SpotlightStep extends ShowMe {
  title: string;
  description: string;
}

export interface SpotlightLabels {
  done: string;
  next?: string;
  previous?: string;
  /** Template with {{current}} and {{total}}. */
  progress?: string;
  /** Badge above the title, e.g. "v2.1.1": which release the stop belongs to. */
  version?: string;
}

interface SpotlightOptions {
  labels: SpotlightLabels;
  signal: AbortSignal;
  progress?: { index: number; total: number };
}

export type SpotlightOutcome = "next" | "previous" | "closed" | "no-anchor";

/** Render one stop on the current page and wait for the user's action. */
export async function spotlight(
  step: SpotlightStep,
  { labels, signal, progress }: SpotlightOptions
): Promise<SpotlightOutcome> {
  const element = await waitForAnchor(step.anchor, signal);
  if (signal.aborted) return "closed";
  if (!element) return "no-anchor";

  const { driver } = await import("driver.js");
  await import("driver.js/dist/driver.css");
  if (signal.aborted) return "closed";

  const isFirst = !progress || progress.index === 0;
  const isLast = !progress || progress.index === progress.total - 1;
  return new Promise((resolve, reject) => {
    let finished = false;
    const abort = () => finish("closed");
    const finish = (outcome: SpotlightOutcome) => {
      if (finished) return;
      finished = true;
      signal.removeEventListener("abort", abort);
      window.removeEventListener("keyup", navigate);
      tour.destroy();
      if (!signal.aborted && element.isConnected) focusFeature(element);
      resolve(outcome);
    };
    const navigate = (event: KeyboardEvent) => {
      if (event.key === "ArrowRight") finish("next");
      else if (event.key === "ArrowLeft" && !isFirst) finish("previous");
    };
    const tour = driver({
      animate: true,
      // The controller owns cross-page steps; driver.js only sees one step.
      allowKeyboardControl: false,
      overlayOpacity: 0.55,
      stagePadding: 8,
      stageRadius: 8,
      showButtons: progress ? ["previous", "next", "close"] : ["next", "close"],
      disableButtons: isFirst ? ["previous"] : [],
      showProgress: Boolean(progress),
      progressText: labels.progress,
      nextBtnText: labels.next ?? labels.done,
      prevBtnText: labels.previous ?? "",
      doneBtnText: isLast ? labels.done : (labels.next ?? labels.done),
      popoverClass: "eneo-spotlight",
      steps: [{ element, popover: { title: step.title, description: step.description } }],
      onPopoverRender: (popover) => {
        if (labels.version) {
          const badge = document.createElement("span");
          badge.className = "eneo-spotlight-version";
          badge.textContent = labels.version;
          popover.title.before(badge);
        }
        if (progress) {
          popover.progress.textContent = (labels.progress ?? "{{current}} / {{total}}")
            .replace("{{current}}", String(progress.index + 1))
            .replace("{{total}}", String(progress.total));
          if (!isFirst) {
            popover.previousButton.disabled = false;
            popover.previousButton.classList.remove("driver-popover-btn-disabled");
          }
        }
        // driver.js applies its default focus after this render hook returns.
        queueMicrotask(() => {
          if (!signal.aborted && popover.wrapper.isConnected) popover.nextButton.focus();
        });
      },
      onNextClick: () => finish("next"),
      onPrevClick: () => {
        if (!isFirst) finish("previous");
      },
      // onDestroyed is not called when closed during the initial animation.
      // Own completion here, including the close button and overlay dismissal.
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

function focusFeature(element: HTMLElement) {
  const target =
    element.querySelector<HTMLElement>(
      'button, a[href], input, select, textarea, [tabindex]:not([tabindex="-1"])'
    ) ?? element;
  if (target === element && !element.hasAttribute("tabindex"))
    element.setAttribute("tabindex", "-1");
  target.focus({ preventScroll: true });
}

function waitForAnchor(anchor: string, signal: AbortSignal): Promise<HTMLElement | null> {
  return new Promise((resolve) => {
    const finish = (element: HTMLElement | null) => {
      observer.disconnect();
      clearTimeout(timeout);
      signal.removeEventListener("abort", abort);
      resolve(element);
    };
    const check = () => {
      const element = document.querySelector<HTMLElement>(`[data-tour="${anchor}"]`);
      if (element) finish(element);
    };
    const abort = () => finish(null);
    const observer = new MutationObserver(check);
    const timeout = setTimeout(() => finish(null), ANCHOR_WAIT_MS);
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
