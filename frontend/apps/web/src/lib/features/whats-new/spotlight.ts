import { goto } from "$app/navigation";
import { localizeHref } from "$lib/paraglide/runtime";
import type { ShowMe } from "@eneo/whats-new";

const ANCHOR_WAIT_MS = 2500;

/**
 * Navigate to the entry's page and spotlight its `data-tour` anchor with a
 * single driver.js step. Degrades to plain navigation when the anchor never
 * renders (permission, feature flag, redesign that dropped the attribute).
 */
export async function showMe(
  target: ShowMe,
  popover: { title: string; description: string; doneLabel: string }
): Promise<boolean> {
  // The href comes from releases.json (validated as an app path), not a typed route.
  // eslint-disable-next-line svelte/no-navigation-without-resolve -- localizeHref handles routing
  await goto(localizeHref(target.href));

  const element = await waitForAnchor(target.anchor);
  if (!element) return false;

  const { driver } = await import("driver.js");
  await import("driver.js/dist/driver.css");

  // A one-step tour rather than highlight(): highlight() renders no buttons,
  // a step gets the "done" button plus Esc/overlay-click to dismiss.
  const tour = driver({
    animate: true,
    overlayOpacity: 0.55,
    stagePadding: 8,
    stageRadius: 8,
    showButtons: ["next", "close"],
    doneBtnText: popover.doneLabel,
    popoverClass: "eneo-spotlight",
    steps: [
      {
        element,
        popover: { title: popover.title, description: popover.description }
      }
    ],
    // driver.js does not move focus on its own; keyboard and screen-reader
    // users need to land in the popover and be returned to the feature after.
    onHighlighted: () => {
      document.querySelector<HTMLElement>(".eneo-spotlight .driver-popover-next-btn")?.focus();
    },
    onDestroyed: () => {
      focusFeature(element);
    }
  });
  element.scrollIntoView({ block: "center", behavior: "smooth" });
  tour.drive();
  return true;
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
