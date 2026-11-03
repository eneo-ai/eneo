import type { Page } from "@playwright/test";
import { expect, test } from "./csp";
import { STORAGE_STATE } from "../playwright.config";
import { apiPost, createSpace, uniqueName } from "./helpers";
import { openRoute } from "./responsive-fixtures";

test.skip(!process.env.E2E_BASE_URL, "Requires the FastAPI-served Vite build");

/*
 * What opens and closes takes the time of the Eneo motion scale (globals.css; the owner's
 * "Rörelse, touch och prestanda" board): a menu opens in 165 ms and closes at once, a drawer, a
 * sheet and a dialog open in 225. With the system's "reduce motion" on, nothing moves or changes
 * size (WCAG 2.3.3, and 2.2.2 for anything that would keep moving); the one thing allowed is an
 * opacity-only fade of at most 200 ms, which Astryx plays on touch for its layers, the SideNav
 * rail and what a disclosure moves. Measured as the browser runs it (document.getAnimations()), a
 * few ms after the control is pressed.
 */

/** `name` is empty for a Web Animation (Astryx's layout motion); `props` is what it changes. */
type Run = { name: string; ms: number; on: string; props: string[] };

/** What runs now; with `within`, only inside the first element that selector matches. */
const running = (page: Page, within?: string): Promise<Run[]> =>
  page.evaluate((within) => {
    const area = within ? document.querySelector(within) : null;
    if (within && !area) throw new Error(`Nothing matches ${within}`);
    return (
      document
        .getAnimations()
        .filter((animation) => !area || area.contains((animation.effect as KeyframeEffect).target))
        .map((animation) => {
          const effect = animation.effect as KeyframeEffect;
          const target = effect.target as HTMLElement | null;
          return {
            name:
              (animation as CSSAnimation).animationName ??
              (animation as CSSTransition).transitionProperty ??
              "",
            ms: Number(effect.getTiming().duration),
            on: `${target?.tagName.toLowerCase()}.${String(target?.className ?? "").split(" ")[0]}`,
            props: [...new Set(effect.getKeyframes().flatMap(Object.keys))].filter(
              (key) => !["offset", "computedOffset", "easing", "composite"].includes(key)
            )
          };
        })
        // Spinners and skeletons loop for as long as something loads; they are not what opens.
        .filter((run) => !/spin|pulse|skeleton/i.test(run.name + run.on))
    );
  }, within);

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

      // A page with a sidebar: the assistant catalogue has none, as in the Svelte app.
      await openRoute(page, "/spaces/list", true);
      await press("drawer open", () =>
        page
          .getByRole("button", { name: /öppna menyn/i })
          .first()
          .click()
      );
      await press("drawer close", () => page.keyboard.press("Escape"));

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
      expect(durations(seen["sheet open"]!, /dialog|bottom-sheet/).sort(), "sheet open").toEqual([
        225, 225
      ]);
    }
  );
}

/*
 * The desktop nav collapses to an icon rail and back. Astryx lays the new width out at once and
 * plays the change over it: a copy of the old rail closed by a clip while the new one fades in,
 * on a spring. With reduce motion it only fades on a coarse pointer and lands at once with a
 * mouse. Measured inside the nav's wrapper, which holds that copy too.
 */
const RAIL = 'nav[aria-label="Ytans meny"]';
const RAIL_AREA = `:has(> ${RAIL})`;
// The toggle's own press scale is a CSS transition, named for its property; the rail's motion
// is Web Animations, which have no name.
const scripted = (runs: Run[]) => runs.filter((run) => run.name === "");

for (const { title, reduced, touch } of [
  { title: "the rail glides by clip and opacity", reduced: false, touch: false },
  { title: "the rail at most fades with reduced motion on touch", reduced: true, touch: true },
  { title: "the rail changes at once with reduced motion and a mouse", reduced: true, touch: false }
]) {
  test(title, { tag: ["@vite", "@motion"] }, async ({ browser, baseURL }) => {
    const context = await browser.newContext({
      baseURL,
      storageState: STORAGE_STATE,
      // Below 1280 px the nav starts as the rail, so the press expands it; at 1280 it collapses.
      viewport: touch ? { width: 1024, height: 768 } : { width: 1280, height: 800 },
      hasTouch: touch,
      isMobile: touch,
      reducedMotion: reduced ? "reduce" : "no-preference"
    });
    const page = await context.newPage();
    // A page with a sidebar: the assistant catalogue has none, as in the Svelte app.
    await openRoute(page, "/spaces/list", true);
    // Astryx chooses the fade by the primary pointer, so the emulation has to report it.
    const coarse = await page.evaluate(() => matchMedia("(pointer: coarse)").matches);
    expect(coarse, "a coarse pointer").toBe(touch);

    const toggle = page.getByRole("button", { name: /^Fäll (ihop|ut) sidomenyn$/ });
    const expanded = await toggle.getAttribute("aria-expanded");
    await toggle.click();
    await page.waitForTimeout(30);
    const runs = (await running(page, RAIL_AREA)).filter((run) => run.ms > 1);
    await page.waitForTimeout(800);
    const left = await running(page, RAIL_AREA);
    const copies = await page.locator(RAIL).count();
    await expect(toggle).toHaveAttribute("aria-expanded", expanded === "true" ? "false" : "true");
    await context.close();

    if (!reduced) {
      const glide = scripted(runs);
      // A spring, so its length is computed: a band, never an exact number.
      const longest = Math.max(0, ...glide.map((run) => run.ms));
      expect(longest, "the rail glides").toBeGreaterThan(200);
      expect(longest, "the rail glides").toBeLessThan(1000);
      // Nothing animates a size or a position: only the clip and the opacity change.
      expect([...new Set(glide.flatMap((run) => run.props))].sort(), "glide").toEqual([
        "clipPath",
        "opacity"
      ]);
    } else if (touch) {
      // Astryx may fade the change on touch, or make it at once; either is allowed.
      expect(
        runs.filter((run) => run.ms > 200 || run.props.join() !== "opacity"),
        "only opacity, within 200 ms"
      ).toEqual([]);
    } else {
      expect(runs, "the rail changes at once").toEqual([]);
    }
    expect(scripted(left), "the motion has ended").toEqual([]);
    expect(copies, "the old rail's copy is gone").toBe(1);
  });
}

/*
 * A disclosure (Astryx Collapsible, with the page panel's handle) opens and closes over the same
 * spring: what follows it glides from its old place on a `translate` and the content clips open
 * or shut. With reduce motion that is an opacity fade on touch and nothing with a mouse. Astryx
 * animates only what is in view, so the trigger is scrolled to the middle of the screen first.
 */
let templateEditor: Promise<string> | undefined;

/** An assistant editor that shows the document-template choice, a Collapsible: made once. */
const templateChoiceEditor = (page: Page) =>
  (templateEditor ??= (async () => {
    // The choice is there while the organisation's file creation is on.
    await page.goto("/admin/tools?tab=functions");
    const fileCreation = page.getByRole("region", { name: "Skapa fil", exact: true });
    const turnOn = fileCreation.getByRole("button", { name: "Slå på", exact: true });
    const library = fileCreation.getByRole("region", { name: "Dokumentmallar", exact: true });
    await expect(turnOn.or(library)).toBeVisible();
    if (await turnOn.isVisible()) await turnOn.click();
    await expect(library).toBeVisible();
    const space = await createSpace(page, uniqueName("Rörelse"));
    const offered = await page.evaluate(async (space) => {
      const session = await fetch("/api/v1/auth/session/");
      const generation = session.headers.get("Eneo-Session-Generation");
      if (session.status !== 204 || !generation) throw new Error("Fixture session probe failed");
      const response = await fetch(`/api/v1${space}/`, {
        method: "PATCH",
        headers: { "content-type": "application/json", "Eneo-Session-Generation": generation },
        body: JSON.stringify({ enabled_capabilities: ["file_creation"] })
      });
      return response.status;
    }, space);
    expect(offered).toBe(200);
    const assistant = await apiPost(page, `${space}/applications/assistants/`, {
      name: uniqueName("Rörelse")
    });
    await apiPost(page, `/assistants/${assistant}/`, {
      enabled_capabilities: ["file_creation"],
      document_template: { mode: "builtin", template_id: null }
    });
    return `${space}/assistants/${assistant}/edit?section=capabilities`;
  })());

for (const { title, reduced, touch } of [
  { title: "a disclosure glides what follows and clips its content", reduced: false, touch: false },
  { title: "a disclosure at most fades with reduced motion on touch", reduced: true, touch: true },
  { title: "a disclosure is instant with reduced motion and a mouse", reduced: true, touch: false }
]) {
  test(title, { tag: ["@vite", "@motion"] }, async ({ browser, baseURL }) => {
    test.setTimeout(2 * 60_000);
    const context = await browser.newContext({
      baseURL,
      storageState: STORAGE_STATE,
      viewport: touch ? { width: 390, height: 844 } : { width: 1280, height: 800 },
      hasTouch: touch,
      isMobile: touch,
      reducedMotion: reduced ? "reduce" : "no-preference"
    });
    const page = await context.newPage();
    await openRoute(page, await templateChoiceEditor(page), true);
    const coarse = await page.evaluate(() => matchMedia("(pointer: coarse)").matches);
    expect(coarse, "a coarse pointer").toBe(touch);

    const trigger = page
      .locator("#assistant-document-template")
      .getByRole("button", { name: "Ändra dokumentmall" });
    await trigger.evaluate((element) => element.scrollIntoView({ block: "center" }));
    const toggle = async () => {
      await trigger.click();
      await page.waitForTimeout(30);
      const runs = (await running(page, "#main-content")).filter((run) => run.ms > 1);
      await page.waitForTimeout(800);
      return runs;
    };
    const opened = await toggle();
    await expect(trigger).toHaveAttribute("aria-expanded", "true");
    const closed = await toggle();
    await expect(trigger).toHaveAttribute("aria-expanded", "false");
    const left = await running(page, "#main-content");
    await context.close();

    for (const [what, runs] of [
      ["open", opened],
      ["close", closed]
    ] as const) {
      if (!reduced) {
        const glide = scripted(runs).map((run) => [...run.props].sort().join());
        expect(glide, `${what}: what follows glides`).toContain("translate");
        expect(glide, `${what}: the content clips`).toContain("clipPath,opacity");
        // Nothing animates a size.
        expect(
          glide.filter((props) => props !== "translate" && props !== "clipPath,opacity"),
          what
        ).toEqual([]);
      } else if (touch) {
        // Astryx may fade the change on touch, or make it at once; either is allowed.
        expect(
          runs.filter((run) => run.ms > 200 || run.props.join() !== "opacity"),
          `${what}: only opacity, within 200 ms`
        ).toEqual([]);
      } else {
        expect(runs, `${what} changes at once`).toEqual([]);
      }
    }
    expect(scripted(left), "the motion has ended").toEqual([]);
  });
}
