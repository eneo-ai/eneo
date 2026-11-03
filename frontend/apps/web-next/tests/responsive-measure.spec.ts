import type { Page } from "@playwright/test";
import { expect, test } from "./csp";
import { measure, type Violation } from "./responsive-measure";

/*
 * The responsive contract's measure (tests/responsive-measure.ts) on small
 * hand-made pages, so it needs no stack. The config only asks for the variable:
 * `E2E_BASE_URL=http://127.0.0.1:1 bun run test:e2e tests/responsive-measure.spec.ts --no-deps`.
 */

// Hand-made pages have no session to check.
test.use({
  viewport: { width: 390, height: 844 },
  hasTouch: true,
  storageState: { cookies: [], origins: [] },
  sharedSession: async ({}, run) => run()
});

const BUTTON = "flex:none;width:96px;height:48px";

async function violationsOn(page: Page, body: string) {
  await page.setContent(`<body style="margin:0">${body}</body>`);
  return (await measure(page)).violations;
}

const outside = (violations: Violation[]) =>
  violations.filter((violation) => violation.kind === "outside").map(({ key }) => key);

test.describe("the responsive measure", () => {
  test("flags a control past the screen's edge", async ({ page }) => {
    const violations = await violationsOn(
      page,
      `<button style="position:absolute;left:400px;top:8px;${BUTTON}">Past</button>`
    );
    expect(outside(violations)).toEqual(["button:past"]);
  });

  test("passes a control that a scroller inside the screen brings into view", async ({ page }) => {
    const violations = await violationsOn(
      page,
      `<div style="margin:8px 16px;width:300px;overflow-x:auto">
        <div style="display:flex;width:800px">
          <button style="${BUTTON}">First</button>
          <button style="${BUTTON};margin-left:500px">Past</button>
        </div>
      </div>`
    );
    expect(outside(violations)).toEqual([]);
  });

  test("flags a control in a scroller that itself runs past the screen", async ({ page }) => {
    const violations = await violationsOn(
      page,
      `<div style="margin:8px 16px;width:500px;overflow-x:auto">
        <div style="display:flex;width:800px">
          <button style="${BUTTON}">First</button>
          <button style="${BUTTON};margin-left:500px">Past</button>
        </div>
      </div>`
    );
    expect(outside(violations)).toEqual(["button:past"]);
  });

  test("flags a control before its scroller's start, which no scroll reaches", async ({ page }) => {
    // What a centred strip too narrow for its tabs does to its first ones.
    const violations = await violationsOn(
      page,
      `<div style="margin:8px 16px;width:300px;overflow-x:auto">
        <div style="display:flex;width:600px;margin-left:-150px">
          <button style="${BUTTON}">Before</button>
          <button style="${BUTTON};margin-left:400px">Reachable</button>
        </div>
      </div>`
    );
    expect(outside(violations)).toEqual(["button:before"]);
  });

  test("still finds a small target and an overlap, in a scroller or not", async ({ page }) => {
    const violations = await violationsOn(
      page,
      `<div style="margin:8px 16px;width:300px;overflow-x:auto">
        <div style="display:flex;width:800px">
          <button style="flex:none;width:30px;height:30px;margin-left:600px">Tiny</button>
        </div>
      </div>
      <div style="position:relative;margin:8px 16px;height:48px">
        <button style="position:absolute;left:0;${BUTTON}">Under</button>
        <button style="position:absolute;left:60px;${BUTTON}">Over</button>
      </div>`
    );
    expect(violations).toEqual(
      expect.arrayContaining([
        { kind: "small", key: "button:tiny" },
        { kind: "overlap", key: "button:under x button:over" }
      ])
    );
    expect(outside(violations)).toEqual([]);
  });

  test("counts an overlap only where both controls show, not what a strip has scrolled away", async ({
    page
  }) => {
    // A tab strip scrolled to its current tab: its first tab runs under the side rail
    // beside it, where the strip clips it and a finger lands on the rail.
    await page.setContent(
      `<body style="margin:0">
        <button style="position:fixed;left:8px;top:8px;width:48px;height:48px">Rail</button>
        <div id="strip" style="margin:8px 0 0 80px;width:200px;overflow-x:auto">
          <div style="display:flex;width:600px">
            <button style="${BUTTON}">First</button>
            <button style="${BUTTON};margin-left:300px">Current</button>
          </div>
        </div>
      </body>`
    );
    const overlaps = async () =>
      (await measure(page)).violations.filter((violation) => violation.kind === "overlap");
    expect(await overlaps()).toEqual([]);
    await page.locator("#strip").evaluate((strip) => (strip.scrollLeft = 60));
    expect(await overlaps()).toEqual([]);
    // Unclipped, the same tab over the rail is an overlap.
    await page.locator("#strip").evaluate((strip) => {
      strip.style.overflowX = "visible";
      (strip.firstElementChild as HTMLElement).style.marginLeft = "-60px";
    });
    expect(await overlaps()).toEqual([{ kind: "overlap", key: "button:rail x button:first" }]);
  });

  test("measures a radio by the label that checks it, and only by that", async ({ page }) => {
    const small = (violations: Violation[]) =>
      violations.filter((violation) => violation.kind === "small").map(({ key }) => key);
    // A whole-card label around a 13 px radio: a tap anywhere on the card checks it.
    expect(
      small(
        await violationsOn(
          page,
          `<label style="display:block;margin:8px 16px;height:60px"><input type="radio" style="width:13px;height:13px"> Card</label>`
        )
      )
    ).toEqual([]);
    // A label too small to tap is still reported.
    expect(
      small(
        await violationsOn(
          page,
          `<label style="display:block;margin:8px 16px;height:20px"><input type="radio" style="width:13px;height:13px"> Card</label>`
        )
      )
    ).toEqual(["input:"]);
    // A label whose for= points at another control does not check this one.
    expect(
      small(
        await violationsOn(
          page,
          `<label for="other" style="display:block;margin:8px 16px;height:60px"><input type="radio" style="width:13px;height:13px"> Card</label><button id="other" style="display:block;margin:8px 16px;width:96px;height:48px">Other</button>`
        )
      )
    ).toEqual(["input:"]);
  });

  test("measures a typeahead's combobox by its frame", async ({ page }) => {
    const violations = await violationsOn(
      page,
      `<div class="astryx-typeahead" style="margin:8px 16px;height:44px;width:300px"><input role="combobox" style="width:200px;height:23px;margin:10px;font-size:16px"></div>`
    );
    expect(violations.filter((violation) => violation.kind === "small")).toEqual([]);
  });

  test("measures a number input's spinbutton by its frame, and still finds a small frame", async ({
    page
  }) => {
    const small = (violations: Violation[]) =>
      violations.filter((violation) => violation.kind === "small").map(({ key }) => key);
    const markup = (height: number) =>
      `<div class="astryx-number-input" style="margin:8px 16px;height:${height}px;width:300px"><input role="spinbutton" style="width:200px;height:23px;margin:4px 10px;font-size:16px"></div>`;
    expect(small(await violationsOn(page, markup(44)))).toEqual([]);
    expect(small(await violationsOn(page, markup(32)))).toEqual(["input[spinbutton]:"]);
  });

  test("finds text cut off at the bottom only when asked, and not a line clamp", async ({
    page
  }) => {
    await page.setContent(
      `<body style="margin:0"><div id="cut" style="margin:8px 16px;width:200px;height:20px;overflow:hidden">Lorem ipsum dolor sit amet consectetur adipiscing elit sed do eiusmod tempor incididunt</div><p id="clamp" style="margin:8px 16px;width:200px;display:-webkit-box;-webkit-line-clamp:1;-webkit-box-orient:vertical;overflow:hidden">Lorem ipsum dolor sit amet consectetur adipiscing elit sed do eiusmod tempor incididunt</p></body>`
    );
    const kinds = async (vertical: boolean) =>
      (await measure(page, { vertical })).violations
        .filter((violation) => violation.kind === "clippedY")
        .map(({ key }) => key);
    expect(await kinds(false)).toEqual([]);
    expect(await kinds(true)).toEqual(["y div:lorem ipsum dolor sit amet c"]);
  });

  test("leaves out what a closed details holds", async ({ page }) => {
    const small = (violations: Violation[]) =>
      violations.filter((violation) => violation.kind === "small").map(({ key }) => key);
    const markup = (open: string) =>
      `<details ${open} style="margin:8px 16px"><summary style="min-height:44px;display:block">More</summary><input style="display:block;width:200px;height:20px"></details>`;
    // Closed, the field is not on the screen; open, it is a target under 44 px.
    expect(small(await violationsOn(page, markup("")))).toEqual([]);
    expect(small(await violationsOn(page, markup("open")))).toEqual(["input:"]);
  });
});
