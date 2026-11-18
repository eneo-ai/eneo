import type { Page } from "@playwright/test";
import { expect, test } from "./csp";
import { contrastProbe } from "./contrast-probe";
import { leftEdgeProbe } from "./left-edge-probe";
import { selectedProbe } from "./selected-probe";
import type { Cell, Probe } from "./ui-probes";

/*
 * The UI probes (tests/ui-probes.ts) on small hand-made pages, so they need no stack: each
 * finds what was planted and passes the page without it. The config only asks for the variable:
 * `E2E_BASE_URL=http://127.0.0.1:1 bun run test:e2e tests/ui-probes.spec.ts --no-deps`.
 */

// Hand-made pages have no session to check.
test.use({ storageState: { cookies: [], origins: [] }, sharedSession: async ({}, run) => run() });

const DESK: Cell = { viewport: { width: 1280, height: 800 }, theme: "light", touch: false };
const DARK: Cell = { ...DESK, theme: "dark" };
const PHONE: Cell = { viewport: { width: 390, height: 844 }, theme: "light", touch: true };

async function run(page: Page, probe: Probe, body: string, cell = DESK, background = "#fff") {
  await page.setViewportSize(cell.viewport);
  await page.setContent(
    `<body style="margin:0;background:${background};font:16px/1.4 sans-serif">${body}</body>`
  );
  const problems = await probe(page, cell);
  return {
    failures: problems.filter((problem) => !problem.review).map(({ key }) => key),
    reviews: problems.filter((problem) => problem.review).map(({ key }) => key)
  };
}

const SAVE = `<style>.b{color:#fff;background:#0b5cad;border:0;padding:12px}</style>`;

test.describe("the contrast probe", () => {
  test("fails faint text and passes dark text", async ({ page }) => {
    const { failures } = await run(
      page,
      contrastProbe,
      `<p>Dark</p><p style="color:#aaa">Faint</p>`
    );
    expect(failures).toEqual(["text p:faint"]);
  });

  test("reads a one-colour gradient as a flat overlay", async ({ page }) => {
    const { failures, reviews } = await run(
      page,
      contrastProbe,
      `<div style="background-image:linear-gradient(#777,#777)"><span style="color:#888">On grey</span></div>`
    );
    expect(failures).toEqual(["text span:on grey"]);
    expect(reviews).toEqual([]);
  });

  test("leaves text over a real gradient or an image for review, not a failure", async ({
    page
  }) => {
    const { failures, reviews } = await run(
      page,
      contrastProbe,
      `<div style="background-image:linear-gradient(#000,#fff)"><span style="color:#888">Fade</span></div>`
    );
    expect(failures).toEqual([]);
    expect(reviews).toEqual(["text span:fade"]);
  });

  test("dims text by its ancestors' opacity, and holds large text to 3:1", async ({ page }) => {
    const { failures } = await run(
      page,
      contrastProbe,
      `<div style="opacity:.4"><p style="color:#555">Dimmed</p></div><p style="color:#555">Solid</p>
      <p style="font-size:24px;color:#888">Large</p><p style="color:#888">Small</p>`
    );
    expect(failures).toEqual(["text p:dimmed", "text p:small"]);
  });

  test("leaves paint inside a translucent group for review, not a failure", async ({ page }) => {
    // Rendered: black text over #808080, 5.28:1; fading text and panel apart gives 2.61:1.
    const { failures, reviews } = await run(
      page,
      contrastProbe,
      `<div style="opacity:.5;background:#fff"><p style="color:#000">Panel</p></div>`,
      DESK,
      "#000"
    );
    expect(failures).toEqual([]);
    expect(reviews).toEqual(["text p:panel"]);
  });

  test("leaves a translucent element that paints its own background for review", async ({
    page
  }) => {
    const { failures, reviews } = await run(
      page,
      contrastProbe,
      `<p style="opacity:.5;background:#fff;color:#000">Panel</p>`,
      DESK,
      "#000"
    );
    expect(failures).toEqual([]);
    expect(reviews).toEqual(["text p:panel"]);
  });

  test("fails a field boundary, a placeholder and an icon-only button under their minimum", async ({
    page
  }) => {
    const icon = (stroke: string) =>
      `<svg width="24" height="24" viewBox="0 0 24 24"><path d="M4 4L20 20" stroke="${stroke}" stroke-width="2"/></svg>`;
    const { failures } = await run(
      page,
      contrastProbe,
      `<style>input::placeholder{color:#bbb}</style>
      <input aria-label="Faint field" style="border:1px solid #ddd">
      <input aria-label="Field" style="border:1px solid #767676">
      <input aria-label="Search" placeholder="Search" style="border:1px solid #767676">
      <button aria-label="Close" style="background:none;border:0">${icon("#ccc")}</button>
      <button aria-label="Open" style="background:none;border:0">${icon("#555")}</button>`
    );
    expect(failures.sort()).toEqual([
      "boundary input:faint field",
      "icon button:close",
      "placeholder input:search"
    ]);
  });

  test("judges a field by the box that draws its boundary", async ({ page }) => {
    const { failures } = await run(
      page,
      contrastProbe,
      `<div style="border:1px solid #767676;padding:4px"><textarea aria-label="Message" style="border:0"></textarea></div>
      <span style="position:relative;display:inline-block">
        <input type="checkbox" aria-label="Faint check" style="position:absolute;inset:0;margin:0;opacity:0">
        <span style="display:block;width:20px;height:20px;border:1px solid #ddd"></span>
      </span>`
    );
    expect(failures).toEqual(["boundary input:faint check"]);
  });

  test("skips the hidden native select a custom select mirrors for its form", async ({ page }) => {
    // Radix Select: the visible trigger is a button; a 1 px aria-hidden <select> beside it,
    // transparent under Tailwind's reset, only carries the value to the form. The first
    // painted box above it is not its boundary.
    const { failures } = await run(
      page,
      contrastProbe,
      `<div style="background:#f4f4f4;padding:8px"><div style="position:relative">
        <button role="combobox" aria-label="Scope" style="border:1px solid #767676;background:#fff">Alla</button>
        <select aria-hidden="true" tabindex="-1" style="position:absolute;background:transparent;border:0;width:1px;height:1px;padding:0;margin:-1px;overflow:hidden;clip:rect(0,0,0,0);white-space:nowrap"><option>Alla</option><option>Organisation</option></select>
      </div></div>`
    );
    expect(failures).toEqual([]);
  });

  test("skips the text of a disabled or aria-disabled control's label", async ({ page }) => {
    const { failures } = await run(
      page,
      contrastProbe,
      `<label style="opacity:.4"><input type="radio" disabled> Object storage <span>Not configured</span></label>
      <label style="opacity:.4"><input type="checkbox" role="switch" aria-disabled="true"> Follow apps</label>
      <label style="opacity:.4"><input type="radio"> Faint but active</label>`
    );
    expect(failures).toEqual(["text label:faint but active"]);
  });

  test("skips a disabled control and text under something else", async ({ page }) => {
    const { failures } = await run(
      page,
      contrastProbe,
      `<button disabled style="color:#ccc">Off</button><p style="color:#ccc">Under</p>
      <div style="position:fixed;inset:0 0 auto 0;height:200px;background:#fff"></div>`
    );
    expect(failures).toEqual([]);
  });

  test("forces hover only where a pointer hovers, and leaves the page at rest", async ({
    page
  }) => {
    const body = `${SAVE}<style>.b:hover{background:#9ec5f0}</style><button class="b">Save</button>`;
    expect((await run(page, contrastProbe, body)).failures).toEqual(["text:hover button:save"]);
    const background = await page
      .locator("button")
      .evaluate((button) => getComputedStyle(button).backgroundColor);
    expect(background).toBe("rgb(11, 92, 173)");
    expect((await run(page, contrastProbe, body, PHONE)).failures).toEqual([]);
  });

  test("forces pressed and keyboard focus on a touch screen too", async ({ page }) => {
    const { failures } = await run(
      page,
      contrastProbe,
      `${SAVE}<style>.s:active,.g:focus-visible{background:#9ec5f0}</style>
      <button class="b s">Save</button><button class="b g">Go</button>`,
      PHONE
    );
    expect(failures.sort()).toEqual(["text:active button:save", "text:focus-visible button:go"]);
  });
});

const TABS = (selected: string, other: string, track = "#eee") =>
  `<div role="tablist" aria-label="Views" style="display:flex;gap:4px;background:${track};padding:4px">
    <button role="tab" aria-selected="true" style="position:relative;border:0;padding:8px;${selected}">One</button>
    <button role="tab" aria-selected="false" style="position:relative;border:0;padding:8px;${other}">Two</button>
  </div>`;

test.describe("the selected-state probe", () => {
  test("leaves a selected tab told apart by a faint plate and a near colour for review", async ({
    page
  }) => {
    const { failures, reviews } = await run(
      page,
      selectedProbe,
      TABS("background:#fff;color:#222", "background:none;color:#555")
    );
    expect(failures).toEqual([]);
    expect(reviews).toEqual(["selected div[tablist]:views"]);
  });

  test("passes a selected tab with an indicator bar its siblings hide", async ({ page }) => {
    const bar = (opacity: number) =>
      `<span style="position:absolute;inset:auto 8px 0 8px;height:2px;background:#0b5cad;opacity:${opacity}"></span>`;
    const { failures, reviews } = await run(
      page,
      selectedProbe,
      TABS("background:none;color:#222", "background:none;color:#555")
        .replace(">One<", `>One${bar(1)}<`)
        .replace(">Two<", `>Two${bar(0)}<`)
    );
    expect(failures).toEqual([]);
    expect(reviews).toEqual([]);
  });

  test("fails a selected plate darker than its track in dark mode, not a lighter one", async ({
    page
  }) => {
    const option = (plate: string) =>
      TABS(
        `background:${plate};box-shadow:inset 0 0 0 1px #9aa1ab;color:#fff`,
        "background:none;color:#ccc",
        "#3a3f47"
      );
    const darker = await run(page, selectedProbe, option("#1c2027"), DARK, "#121212");
    expect(darker.failures).toEqual(["pressed div[tablist]:views"]);
    const lighter = await run(page, selectedProbe, option("#5a616b"), DARK, "#121212");
    expect(lighter.failures).toEqual([]);
  });

  test("leaves a selected plate painted by a real gradient for review, not a failure", async ({
    page
  }) => {
    // The dark background colour is hidden under the opaque, lighter gradient.
    const { failures, reviews } = await run(
      page,
      selectedProbe,
      TABS(
        "background:#1c2027 linear-gradient(#5a616b,#6a717b);box-shadow:inset 0 0 0 1px #9aa1ab;color:#fff",
        "background:none;color:#ccc",
        "#3a3f47"
      ),
      DARK,
      "#121212"
    );
    expect(failures).toEqual([]);
    expect(reviews).toEqual(["selected div[tablist]:views"]);
  });
});

// The shared column (PAGE_COLUMN) with a list row whose hover surface reaches 8 px into the gutter.
const PAGE = (header: string, rows: string, second = "") =>
  `<main><div style="padding:16px">
    <div class="mx-auto w-full max-w-6xl" style="max-width:1152px;margin:0 auto">${header}${rows}</div>
  </div>${second}</main>`;
const ROW = `<ul class="astryx-list" style="list-style:none;margin:0;padding:0"><li class="astryx-item" style="padding:8px;margin-left:-8px">Row</li></ul>`;

test.describe("the left-edge probe", () => {
  test("passes a heading and a first row on the column's edge", async ({ page }) => {
    const { failures } = await run(
      page,
      leftEdgeProbe,
      PAGE(`<h1 style="margin:0">Title</h1>`, ROW)
    );
    expect(failures).toEqual([]);
  });

  test("fails a row inset from the edge and an indented heading", async ({ page }) => {
    const { failures } = await run(
      page,
      leftEdgeProbe,
      PAGE(`<h1 style="margin:0;padding-left:12px">Title</h1>`, ROW.replace("margin-left:-8px", ""))
    );
    expect(failures).toEqual(["heading h1", "row li.astryx-item"]);
  });

  test("measures a heading from the tile before it, and skips rows inside a card", async ({
    page
  }) => {
    const { failures } = await run(
      page,
      leftEdgeProbe,
      PAGE(
        `<div style="display:flex;gap:16px"><span style="width:48px;height:48px;background:#ccc"></span><h1 style="margin:0">Space</h1></div>`,
        `<div style="border:1px solid #ccc;padding:16px">${ROW.replace("margin-left:-8px", "")}</div>`
      )
    );
    expect(failures).toEqual([]);
  });

  test("leaves a centred heading alone", async ({ page }) => {
    const { failures } = await run(
      page,
      leftEdgeProbe,
      PAGE(`<h1 style="margin:0;text-align:center">Not found</h1>`, "")
    );
    expect(failures).toEqual([]);
  });

  test("fails a second column that starts elsewhere", async ({ page }) => {
    const { failures } = await run(
      page,
      leftEdgeProbe,
      PAGE(
        `<h1 style="margin:0">Title</h1>`,
        ROW,
        `<div style="padding:16px 16px 16px 40px"><div class="mx-auto w-full max-w-6xl" style="max-width:1152px;margin:0 auto">Other</div></div>`
      )
    );
    expect(failures).toEqual(["column 1"]);
  });
});
