import { goto } from "$app/navigation";
import { localizeHref } from "$lib/paraglide/runtime";
import type { ShowMe } from "@eneo/whats-new";
import type { Driver } from "driver.js";

const ANCHOR_WAIT_MS = 2500;

export interface SpotlightStep extends ShowMe {
  title: string;
  description: string;
}

export interface SpotlightLabels {
  done: string;
  next?: string;
  previous?: string;
  /** driver.js template, e.g. "{{current}} of {{total}}". */
  progress?: string;
}

interface SpotlightOptions {
  labels: SpotlightLabels;
  /** Position in a multi-step walkthrough; omitted for a single Show me. */
  progress?: { index: number; total: number };
  onNext?: () => void;
  onPrevious?: () => void;
  onClose?: () => void;
}

/**
 * Navigate to a step's page and spotlight its `data-tour` anchor with
 * driver.js. Resolves false when the anchor never renders (permission,
 * feature flag, redesign that dropped the attribute): the user still lands
 * on the right page, which is the documented fallback.
 */
export async function spotlight(step: SpotlightStep, options: SpotlightOptions): Promise<boolean> {
  // The href comes from releases.json (validated as an app path), not a typed route.
  // eslint-disable-next-line svelte/no-navigation-without-resolve -- localizeHref handles routing
  await goto(localizeHref(step.href));

  const element = await waitForAnchor(step.anchor);
  if (!element) return false;

  const { driver } = await import("driver.js");
  await import("driver.js/dist/driver.css");

  const { labels, progress } = options;
  const isFirst = !progress || progress.index === 0;
  const isLast = !progress || progress.index === progress.total - 1;
  let advanced = false;

  // A one-step drive() rather than highlight(): highlight() renders no
  // buttons, a step gets next/previous/close plus Esc and overlay-click.
  const tour: Driver = driver({
    animate: true,
    overlayOpacity: 0.55,
    stagePadding: 8,
    stageRadius: 8,
    showButtons: progress ? ["previous", "next", "close"] : ["next", "close"],
    disableButtons: isFirst ? ["previous"] : [],
    showProgress: Boolean(progress),
    progressText: labels.progress ?? "{{current}} / {{total}}",
    nextBtnText: labels.next ?? labels.done,
    prevBtnText: labels.previous ?? "",
    doneBtnText: labels.done,
    popoverClass: "eneo-spotlight",
    steps: [
      {
        element,
        popover: {
          title: step.title,
          description: step.description,
          // driver.js counts steps within one drive(); report the walkthrough's.
          ...(progress
            ? {
                onPopoverRender: (popover: { progress: HTMLElement }) => {
                  popover.progress.textContent = (labels.progress ?? "{{current}} / {{total}}")
                    .replace("{{current}}", String(progress.index + 1))
                    .replace("{{total}}", String(progress.total));
                }
              }
            : {})
        }
      }
    ],
    onNextClick: () => {
      advanced = true;
      tour.destroy();
      if (isLast) options.onClose?.();
      else options.onNext?.();
    },
    onPrevClick: () => {
      if (isFirst) return;
      advanced = true;
      tour.destroy();
      options.onPrevious?.();
    },
    // driver.js does not move focus on its own; keyboard and screen-reader
    // users need to land in the popover and be returned to the feature after.
    onHighlighted: () => {
      document.querySelector<HTMLElement>(".eneo-spotlight .driver-popover-next-btn")?.focus();
    },
    onDestroyed: () => {
      focusFeature(element);
      if (!advanced) options.onClose?.();
    }
  });
  element.scrollIntoView({ block: "center", behavior: "smooth" });
  tour.drive();
  return true;
}

/** Single "Show me" from an entry on the What's new page. */
export function showMe(step: SpotlightStep, labels: SpotlightLabels): Promise<boolean> {
  return spotlight(step, { labels });
}

function focusFeature(element: HTMLElement) {
  const target =
    element.querySelector<HTMLElement>(
      'button, a[href], input, select, textarea, [tabindex]:not([tabindex="-1"])'
    ) ?? element;
  if (target === element && !element.hasAttribute("tabindex")) {
    element.setAttribute("tabindex", "-1");
  }
  target.focus({ preventScroll: true });
}

function waitForAnchor(anchor: string): Promise<HTMLElement | null> {
  const selector = `[data-tour="${anchor}"]`;
  return new Promise((resolve) => {
    const started = performance.now();
    const check = () => {
      const found = document.querySelector<HTMLElement>(selector);
      if (found) return resolve(found);
      if (performance.now() - started > ANCHOR_WAIT_MS) return resolve(null);
      requestAnimationFrame(check);
    };
    check();
  });
}
