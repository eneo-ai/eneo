import { visibleEntries } from "@eneo/whats-new";
import type { Locale, Release } from "@eneo/whats-new";
import { reachable, spotlight, type SpotlightLabels, type SpotlightStep } from "./spotlight";

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

/** The steps whose pages this user may open, in order. */
export async function reachableSteps(steps: SpotlightStep[]): Promise<SpotlightStep[]> {
  const hrefs = [...new Set(steps.map((step) => step.href))];
  const allowed = new Map(
    await Promise.all(hrefs.map(async (href) => [href, await reachable(href)] as const))
  );
  return steps.filter((step) => allowed.get(step.href));
}

/**
 * Walk through the steps one page at a time. Pages the user may not open
 * are dropped before the first navigation, so "1 of N" counts what they will
 * actually see; a step whose anchor is not on its page (feature flag) is
 * skipped in the direction of travel; Esc, overlay click or the close button
 * ends the walkthrough where it is. Client-side navigation keeps this
 * closure alive between steps; a full reload ends the walkthrough, which is
 * acceptable.
 */
export async function startTour(
  candidates: SpotlightStep[],
  labels: SpotlightLabels
): Promise<void> {
  const steps = await reachableSteps(candidates);
  if (steps.length === 0) return;
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
      let outcome: Awaited<ReturnType<typeof spotlight>>;
      try {
        outcome = await spotlight(steps[index], {
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
      if (outcome !== "shown") void run(index + direction, direction);
    };

    void run(0, 1);
  });
}
