import { visibleEntries } from "@eneo/whats-new";
import type { Locale, Release } from "@eneo/whats-new";
import { spotlight, type SpotlightLabels, type SpotlightStep } from "./spotlight";

/**
 * The walkthrough is derived from the release's Show me entries, in the
 * order they are listed, restricted to what this user may see. There is no
 * separate tour definition to maintain: the same anchors CI already checks.
 */
export function tourSteps(release: Release, isAdmin: boolean, locale: Locale): SpotlightStep[] {
  return visibleEntries(release, isAdmin).flatMap((entry) =>
    entry.showMe
      ? [
          {
            ...entry.showMe,
            title: entry.title[locale] ?? entry.title.en,
            description: entry.body[locale] ?? entry.body.en
          }
        ]
      : []
  );
}

/**
 * Walk through the steps one page at a time. A step whose anchor is not on
 * its page (permission, feature flag) is skipped in the direction of travel;
 * Esc, overlay click or the close button ends the walkthrough where it is.
 * Client-side navigation keeps this closure alive between steps; a full
 * reload ends the walkthrough, which is acceptable.
 */
export function startTour(steps: SpotlightStep[], labels: SpotlightLabels): Promise<void> {
  if (steps.length === 0) return Promise.resolve();
  return new Promise((resolve, reject) => {
    let active = true;
    const finish = () => {
      if (!active) return;
      active = false;
      resolve();
    };

    const run = async (index: number, direction: 1 | -1) => {
      if (!active) return;
      if (index < 0 || index >= steps.length) return finish();
      let shown: boolean;
      try {
        shown = await spotlight(steps[index], {
          labels,
          progress: { index, total: steps.length },
          onNext: () => void run(index + 1, 1),
          onPrevious: () => void run(index - 1, -1),
          onClose: finish
        });
      } catch (error) {
        // A stop that throws (navigation failure, driver.js not loadable)
        // ends the walkthrough with an error the caller can show.
        active = false;
        reject(error);
        return;
      }
      if (!shown) void run(index + direction, direction);
    };

    void run(0, 1);
  });
}
