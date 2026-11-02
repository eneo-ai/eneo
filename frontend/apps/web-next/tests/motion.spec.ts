import type { Page } from "@playwright/test";
import { expect, test } from "./csp";
import { STORAGE_STATE } from "../playwright.config";
import { openRoute } from "./responsive-fixtures";

test.skip(!process.env.E2E_BASE_URL, "Requires the FastAPI-served Vite build");

/*
 * What opens and closes takes the time of the Eneo motion scale (globals.css; the owner's
 * "Rörelse, touch och prestanda" board): a menu opens in 165 ms and leaves in 125, a drawer, a
 * sheet and a dialog open in 225. With the system's "reduce motion" on, nothing runs at all
 * (WCAG 2.3.3, and 2.2.2 for anything that would keep moving). Measured as the browser runs
 * it (document.getAnimations()), a few ms after the control is pressed.
 */

type Run = { name: string; ms: number; on: string };

const running = (page: Page): Promise<Run[]> =>
  page.evaluate(() =>
    document
      .getAnimations()
      .map((animation) => {
        const effect = animation.effect as KeyframeEffect;
        const target = effect.target as HTMLElement | null;
        return {
          name:
            (animation as CSSAnimation).animationName ??
            (animation as CSSTransition).transitionProperty ??
            "",
          ms: Number(effect.getTiming().duration),
          on: `${target?.tagName.toLowerCase()}.${String(target?.className ?? "").split(" ")[0]}`
        };
      })
      // Spinners and skeletons loop for as long as something loads; they are not what opens.
      .filter((run) => !/spin|pulse|skeleton/i.test(run.name + run.on))
  );

const durations = (runs: Run[], on: RegExp) =>
  runs.filter((run) => on.test(run.on)).map((run) => run.ms);

for (const reduced of [false, true]) {
  test(
    reduced ? "nothing moves with reduced motion" : "overlays open and close on the motion scale",
    { tag: ["@vite", "@motion"] },
    async ({ browser, baseURL }) => {
      test.setTimeout(3 * 60_000);
      const context = await browser.newContext({
        baseURL,
        storageState: STORAGE_STATE,
        viewport: { width: 390, height: 844 },
        hasTouch: true,
        isMobile: true,
        reducedMotion: reduced ? "reduce" : "no-preference"
      });
      const page = await context.newPage();
      const seen: Record<string, Run[]> = {};
      const press = async (what: string, act: () => Promise<unknown>) => {
        await act();
        await page.waitForTimeout(30);
        seen[what] = await running(page);
        await page.waitForTimeout(600);
      };

      await openRoute(page, "/spaces/list", true);
      await press("dialog open", () =>
        page
          .getByRole("main")
          .getByRole("button", { name: /skapa yta/i })
          .first()
          .click()
      );
      await press("dialog close", () => page.keyboard.press("Escape"));
      await press("menu open", () =>
        page
          .getByRole("button", { name: /fler åtgärder för/i })
          .first()
          .click()
      );
      await press("menu close", () => page.keyboard.press("Escape"));

      await openRoute(page, "/dashboard", true);
      await press("drawer open", () =>
        page
          .getByRole("button", { name: /öppna menyn/i })
          .first()
          .click()
      );
      await press("drawer close", () => page.keyboard.press("Escape"));

      await openRoute(page, "/account/api-keys", true);
      await press("legacy menu open", () =>
        page
          .getByRole("button", { name: /fler åtgärder för/i })
          .first()
          .click()
      );
      await press("legacy menu close", () => page.keyboard.press("Escape"));

      await openRoute(page, "/spaces/personal/chat", true);
      await press("sheet open", () =>
        page
          .getByRole("button", { name: /^chattmodell/i })
          .first()
          .click()
      );
      await press("sheet close", () => page.keyboard.press("Escape"));
      await context.close();

      if (reduced) {
        for (const [what, runs] of Object.entries(seen)) {
          expect(
            runs.filter((run) => run.ms > 1),
            `${what} runs nothing`
          ).toEqual([]);
        }
        return;
      }
      expect(durations(seen["dialog open"]!, /dialog/), "dialog open").toEqual([225]);
      expect(durations(seen["menu open"]!, /^div\./), "menu open").toContain(165);
      expect(durations(seen["drawer open"]!, /dialog|div/), "drawer open").toEqual([225, 225]);
      expect(durations(seen["legacy menu open"]!, /bg-popover/), "legacy menu open").toContain(165);
      expect(durations(seen["legacy menu close"]!, /bg-popover/), "legacy menu close").toContain(
        125
      );
      expect(durations(seen["sheet open"]!, /dialog|bottom-sheet/).sort(), "sheet open").toEqual([
        225, 225
      ]);
    }
  );
}
