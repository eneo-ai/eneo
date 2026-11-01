import type { Page } from "@playwright/test";
import { expect, test } from "./csp";
import { measure, type Violation } from "./responsive-measure";

/*
 * The responsive contract's measure (tests/responsive-measure.ts) on small
 * hand-made pages, so it needs no stack. The config only asks for the variable:
 * `E2E_BASE_URL=http://127.0.0.1:1 bun run test:e2e tests/responsive-measure.spec.ts --no-deps`.
 */

test.use({
  viewport: { width: 390, height: 844 },
  hasTouch: true,
  storageState: { cookies: [], origins: [] }
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
});
