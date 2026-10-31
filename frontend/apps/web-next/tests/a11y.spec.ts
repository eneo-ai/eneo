import AxeBuilder from "@axe-core/playwright";
import type { Page } from "@playwright/test";
import type { Schema } from "../src/lib/api/models";
import type { FederationView } from "../src/features/admin/federation/federation";
import { SIDE_NAV_COLLAPSED_COOKIE } from "../src/components/shell/side-nav-preference";
import { assertDocumented, WCAG_22_AA_TAGS } from "../src/test/wcag";
import { expect, test } from "./csp";
import {
  activityPill,
  addActivityToAnswers,
  apiPost,
  apiRequest,
  askChatQuestion,
  auditLogs,
  chatComposer,
  conversationLog,
  createSpace,
  MOCK_REPLY,
  openCreateCollectionDialog,
  sessionResponseHeaders,
  spaceWithWork,
  uniqueName
} from "./helpers";

// Page-level WCAG 2.2 A/AA scans (ACCESSIBILITY.md → How it is enforced).
// axe-core runs in real Chromium, so colour contrast (1.4.3, 1.4.11) and
// target size (2.5.8) are measured on the rendered page, in both colour modes,
// on the desktop and on a phone. Pages are scanned once they show their
// content, and also with a dialog, a menu, the drawer or a panel open. Any
// violation fails the test.
//
// Fix instead of excluding. A region or rule that must be left out of one
// scan goes in that scan's `exclude` / `disableRules`, each with the reason
// and the issue link (ACCESSIBILITY.md → Exceptions); the helper refuses
// entries without them. Nothing is excluded globally.

// Development-only tooling, absent from production builds (what CI scans):
// the Next.js dev overlay and the TanStack Query devtools button.
const DEV_ONLY = ["nextjs-portal", "vite-error-overlay", ".tsqd-parent-container"];

// Best-practice rules on top of the WCAG tags, for ACCESSIBILITY.md rule 1:
// one h1, one main landmark, headings in order. While a modal is open axe
// treats the page behind it as hidden and passes the first two.
const PAGE_STRUCTURE_RULES = ["page-has-heading-one", "landmark-one-main", "heading-order"];

// @axe-core/playwright is typed against the workspace's hoisted playwright-core
// (apps/web's newer Playwright); it only uses Page APIs both versions share.
type AxePage = ConstructorParameters<typeof AxeBuilder>[0]["page"];

type Exceptions = {
  /** Regions to leave out of this scan: selector → reason and issue link. */
  exclude?: Record<string, string>;
  /** Rules to skip in this scan: rule id → reason and issue link. */
  disableRules?: Record<string, string>;
};

// Narrowest content box a table column may have. A collapsed one has none:
// its header cell is only padding wide.
const MIN_COLUMN_CONTENT_PX = 16;

/**
 * Fails on a table column that collapsed (axe has no rule for it). Astryx
 * header cells truncate with `max-width: 0`, which cancels a plain `w-*`
 * width, so the column shrinks until its text wraps a letter per line or a
 * control is clipped (AGENTS.md → Tables). A data table may scroll sideways
 * instead of reflowing (1.4.10); it may not squeeze its columns.
 */
async function expectNoCollapsedTableColumns(page: Page) {
  const collapsed = await page.locator("table th").evaluateAll(
    (cells, minContent) =>
      cells.flatMap((cell) => {
        // A table in a hidden tab panel has no boxes to measure.
        if (cell.getClientRects().length === 0) return [];
        const style = getComputedStyle(cell);
        const content =
          cell.getBoundingClientRect().width -
          parseFloat(style.paddingInlineStart) -
          parseFloat(style.paddingInlineEnd);
        return content < minContent
          ? [`"${cell.textContent?.trim()}": ${Math.round(content)} px`]
          : [];
      }),
    MIN_COLUMN_CONTENT_PX
  );
  expect(collapsed, `Collapsed table columns on ${page.url()}`).toEqual([]);
}

/** Scans the page as it is now: axe, then what axe cannot check. */
async function expectNoAxeViolations(
  page: Page,
  { exclude = {}, disableRules = {} }: Exceptions = {}
) {
  assertDocumented(exclude, (selector) => `Leaving "${selector}" out of the page scan`);
  assertDocumented(disableRules, (rule) => `Skipping the axe rule "${rule}"`);
  // Wait for exposed loading regions. A queued run keeps a decorative skeleton
  // under aria-hidden after the result page has loaded; that state is scanned too.
  await expect(page.locator('[aria-busy="true"]:not([aria-hidden="true"] *)')).toHaveCount(0);

  const rules = Object.fromEntries([
    ...PAGE_STRUCTURE_RULES.map((rule) => [rule, { enabled: true }]),
    ...Object.keys(disableRules).map((rule) => [rule, { enabled: false }])
  ]);
  // options() replaces the run options, so it goes before withTags().
  let builder = new AxeBuilder({ page: page as unknown as AxePage })
    .options({ rules })
    .withTags(WCAG_22_AA_TAGS);
  for (const selector of [...DEV_ONLY, ...Object.keys(exclude)]) {
    builder = builder.exclude(selector);
  }

  // The document title arrives with the route's metadata, which a client
  // navigation streams after the page is interactive; scanning before it
  // lands reports a false "document-title" violation.
  await expect(page).toHaveTitle(/\S/);
  const { violations } = await builder.analyze();
  const report = violations.map((violation) => ({
    rule: violation.id,
    impact: violation.impact,
    help: violation.help,
    helpUrl: violation.helpUrl,
    targets: violation.nodes.map((node) => node.target.join(" "))
  }));
  expect(report, `WCAG 2.2 A/AA violations on ${page.url()}`).toEqual([]);
  await expectNoCollapsedTableColumns(page);
}

/**
 * Reflow (1.4.10): at 320 CSS px wide (1280 px at 400 % zoom) the page
 * scrolls only vertically. Content that needs two dimensions (a data table,
 * code) scrolls sideways inside its own region, never the page: neither the
 * document nor the page panel (main#main-content, the shell's scroll
 * container) may be wider than the viewport.
 */
async function expectNoSidewaysPageScroll(page: Page) {
  const overflow = await page.evaluate(() => {
    const main = document.getElementById("main-content");
    const root = main ?? document.body;
    const right = main ? main.getBoundingClientRect().right : window.innerWidth;
    // To name the culprit when the check fails: what sticks out of the page,
    // not out of a region that scrolls (or clips) on its own. A region clips
    // only the boxes it contains as a containing block, so an absolutely
    // positioned child (a visually hidden text, say) escapes a scroll box
    // that is not positioned; a fixed box is outside the page's width.
    const clipped = (el: Element): boolean => {
      const { position } = getComputedStyle(el);
      if (position === "fixed") return true;
      const next =
        position === "absolute" && el instanceof HTMLElement ? el.offsetParent : el.parentElement;
      if (!next || next === root || !root.contains(next)) return false;
      return getComputedStyle(next).overflowX !== "visible" || clipped(next);
    };
    const offenders = [...root.querySelectorAll("*")]
      .filter((el) => el.getBoundingClientRect().right > right + 1 && !clipped(el))
      .slice(0, 5)
      .map((el) => `${el.tagName.toLowerCase()}.${(el.getAttribute("class") ?? "").slice(0, 60)}`);
    return {
      page: document.documentElement.scrollWidth > window.innerWidth,
      panel: main ? main.scrollWidth > main.clientWidth : false,
      offenders
    };
  });
  expect(
    { page: overflow.page, panel: overflow.panel },
    `Sideways scroll at ${page.viewportSize()?.width} px on ${page.url()}: ${overflow.offenders.join(", ")}`
  ).toEqual({ page: false, panel: false });
}

/**
 * Focus not obscured (2.4.11): no toast covers the focused element. Samples
 * its centre and corners (inset past a rounded border) with elementFromPoint,
 * which finds what is painted on top. Retries briefly: the toasts move out of
 * the way a frame after focus does.
 */
async function expectFocusClearOfToasts(page: Page) {
  await expect(async () => {
    const focus = await page.evaluate(() => {
      const focused = document.activeElement;
      if (!focused || focused === document.body) return { name: "(nothing)", covered: [] };
      const box = focused.getBoundingClientRect();
      const inset = Math.min(8, box.width / 4, box.height / 4);
      const points: [number, number][] = [
        [box.left + box.width / 2, box.top + box.height / 2],
        [box.left + inset, box.top + inset],
        [box.right - inset, box.top + inset],
        [box.left + inset, box.bottom - inset],
        [box.right - inset, box.bottom - inset]
      ];
      return {
        name: (focused.getAttribute("aria-label") ?? focused.textContent ?? "").trim().slice(0, 60),
        covered: points
          .filter(([x, y]) => document.elementFromPoint(x, y)?.closest("[data-sonner-toast]"))
          .map(([x, y]) => `(${Math.round(x)}, ${Math.round(y)})`)
      };
    });
    expect(
      focus.covered,
      `A toast covers the focused element "${focus.name}" at ${focus.covered.join(" ")}`
    ).toEqual([]);
  }).toPass({ timeout: 2_000 });
}

/** Opens a route, waits until it shows real content, then scans it. */
/**
 * The shell is locked to the viewport: pages scroll inside the page panel
 * (main#main-content), never the document, or the whole shell slides up. An
 * absolutely positioned box (visually hidden text) whose containing block is
 * the document, not a region that scrolls, makes the document taller.
 */
async function expectShellHoldsStill(page: Page) {
  const overflow = await page.evaluate(() => {
    const main = document.getElementById("main-content");
    if (!main || getComputedStyle(main).overflowY === "visible") return null;
    const escaped = [...document.body.querySelectorAll("*")]
      .filter(
        (el) =>
          el instanceof HTMLElement &&
          getComputedStyle(el).position === "absolute" &&
          el.offsetParent === document.body &&
          el.getBoundingClientRect().bottom > window.innerHeight + 1
      )
      .slice(0, 5)
      .map((el) => `${el.tagName.toLowerCase()}.${(el.getAttribute("class") ?? "").slice(0, 60)}`);
    return {
      scrolls: document.documentElement.scrollHeight > window.innerHeight + 1,
      escaped
    };
  });
  if (!overflow) return;
  expect(
    overflow.scrolls,
    `The document scrolls under the shell on ${page.url()}: ${overflow.escaped.join(", ")}`
  ).toBe(false);
}

async function scan(page: Page, path: string, ready: () => Promise<void>, exceptions?: Exceptions) {
  await page.goto(path);
  await ready();
  await expectNoAxeViolations(page, exceptions);
  await expectShellHoldsStill(page);
}

/** The personal assistant's greeting, the chat start state's h1 (set once hydrated). */
const GREETING = /^(God (morgon|dag|kväll)|Good (morning|afternoon|evening)), /;

async function chatStartReady(page: Page) {
  await expect(page.getByRole("heading", { level: 1, name: GREETING })).toBeVisible();
  await expect(chatComposer(page)).toBeVisible();
}

/** Asks a question in the personal chat and waits until the answer is saved. */
async function answeredQuestion(page: Page) {
  await page.goto("/spaces/personal/chat");
  await chatStartReady(page);
  await askChatQuestion(page, uniqueName("E2E a11y fråga"));
  await expect(conversationLog(page).getByText(MOCK_REPLY)).toBeVisible({ timeout: 20_000 });
  // Saved and done: the URL names the new conversation and Send is back.
  await expect(page).toHaveURL(/session_id=/);
  await expect(page.getByRole("button", { name: /skicka meddelande|send message/i })).toBeVisible();
}

const ACTIVITY_PANEL = /^(Aktivitet för svaret|Activity for the answer)$/;

/** The Spaces list with its h1 shown: a page that has the whole shell. */
async function spacesList(page: Page) {
  await page.goto("/spaces/list");
  await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
}

/** Opens the ⌘K palette and waits for its first results. */
async function openPalette(page: Page) {
  await page.keyboard.press("ControlOrMeta+k");
  const palette = page.getByRole("dialog", { name: /^(Sök i Eneo|Search Eneo)$/ });
  // "Ny konversation" is always among the actions (a conversation may share its name).
  await expect(
    palette.getByRole("option", { name: /ny konversation|new conversation/i }).first()
  ).toBeVisible();
}

/**
 * The touch layouts the page scans run at: phones and iPads, held both ways.
 * `drawer`: below 1024 px the SideNav is a drawer behind the top bar's menu.
 */
const TOUCH_LAYOUTS = [
  { name: "phone (390 × 844)", viewport: { width: 390, height: 844 }, phone: true, drawer: true },
  {
    name: "iPad portrait (820 × 1180)",
    viewport: { width: 820, height: 1180 },
    phone: false,
    drawer: true
  },
  {
    name: "iPad landscape (1180 × 820)",
    viewport: { width: 1180, height: 820 },
    phone: false,
    drawer: false
  }
] as const;

for (const colorScheme of ["light", "dark"] as const) {
  test.describe(`WCAG 2.2 AA, ${colorScheme} mode`, () => {
    // Reduced motion: no fade-ins mid-scan, so contrast is measured at rest.
    test.use({ colorScheme, contextOptions: { reducedMotion: "reduce" } });

    test.describe("signed out", () => {
      test.use({ storageState: { cookies: [], origins: [] } });

      test("login", async ({ page }) => {
        await scan(page, "/login", async () => {
          await expect(page.locator('input[name="email"]')).toBeVisible();
        });
      });

      test("login failed", async ({ page }) => {
        await scan(page, "/login/failed", async () => {
          await expect(
            page.getByRole("link", { name: /försök logga in igen|try logging in again/i })
          ).toBeVisible();
        });
      });

      test("module login failed", async ({ page }) => {
        await scan(page, "/module-login/failed?reason=module_unavailable", async () => {
          await expect(
            page.getByRole("link", { name: /tillbaka till eneo|back to eneo/i })
          ).toBeVisible();
        });
      });

      test("invitation", async ({ page }) => {
        await scan(page, "/invite/e2e-a11y", async () => {
          await expect(
            page.getByRole("link", { name: /gå till inloggningen|go to the login page/i })
          ).toBeVisible();
        });
      });

      test("login failed with the identity provider's diagnostics", async ({ page }) => {
        await scan(
          page,
          "/login/failed?detailCode=access_denied&correlation=e2e-a11y",
          async () => {
            await expect(
              page.getByText(/autentisering misslyckades|authentication failed/i)
            ).toBeVisible();
          }
        );
      });
    });

    // Signed-in public pages (the frame they share with /login).
    test("activation", async ({ page }) => {
      await scan(page, "/activate", async () => {
        await expect(
          page.getByRole("heading", { level: 1, name: /nästan klar|almost there/i })
        ).toBeVisible();
      });
    });

    test("deactivated organisation", () => {
      test.skip(
        true,
        "/deactivated only renders for a suspended organisation (an active one is sent on into " +
          "the app), and the e2e stack cannot suspend its tenant; its frame is scanned on /login."
      );
    });

    test("personal chat", { tag: "@vite" }, async ({ page }) => {
      await scan(page, "/spaces/personal/chat", () => chatStartReady(page));
    });

    test("chat: an answer with the composer docked, and its activity panel", async ({ page }) => {
      await addActivityToAnswers(page);
      await answeredQuestion(page);
      await expectNoAxeViolations(page);

      await activityPill(page).click();
      const panel = page.getByRole("complementary", { name: ACTIVITY_PANEL });
      await expect(panel.getByRole("tabpanel", { name: /^(Steg|Steps)$/ })).toBeVisible();
      await expectNoAxeViolations(page);

      await panel.getByRole("tab", { name: /^(Källor|Sources)/ }).click();
      await expect(panel.getByRole("link", { name: /E2E-källa/ })).toBeVisible();
      await expectNoAxeViolations(page);
    });

    test("spaces list", { tag: "@vite" }, async ({ page }) => {
      await scan(page, "/spaces/list", async () => {
        await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
      });
    });

    test("a dialog open: Skapa yta", async ({ page }) => {
      await spacesList(page);
      await page
        .getByRole("main")
        .getByRole("button", { name: /skapa yta|create space/i })
        .click();
      const dialog = page.getByRole("dialog", { name: /skapa en ny yta|create a new space/i });
      await expect(dialog.getByLabel(/namn|name/i)).toBeVisible();
      await expectNoAxeViolations(page);
    });

    test("a menu open: the profile menu", async ({ page }) => {
      await spacesList(page);
      await page
        .getByRole("button", { name: /: (konto och inställningar|account and settings)$/ })
        .click();
      await expect(
        page.getByRole("menu").getByRole("menuitem", { name: /^(Mitt konto|My account)$/ })
      ).toBeVisible();
      await expectNoAxeViolations(page);
    });

    test("the command palette open", async ({ page }) => {
      await spacesList(page);
      await openPalette(page);
      await expectNoAxeViolations(page);
    });

    test("assistant catalogue (dashboard)", { tag: "@vite" }, async ({ page }) => {
      await scan(page, "/dashboard", async () => {
        await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
      });
    });

    test(
      "assistant catalogue with the SideNav collapsed to its icon rail",
      { tag: "@vite" },
      async ({ page, baseURL }) => {
        await page
          .context()
          .addCookies([{ name: SIDE_NAV_COLLAPSED_COOKIE, value: "1", url: baseURL! }]);
        await scan(page, "/dashboard", async () => {
          await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
          await expect(
            page.getByRole("button", { name: /fäll ut sidomenyn|expand the side menu/i })
          ).toBeVisible();
        });
      }
    );

    test("dashboard app and result", { tag: "@vite" }, async ({ page }) => {
      const work = await spaceWithWork(page, uniqueName("E2E Dashboard App"));
      for (const width of [1280, 390]) {
        await page.setViewportSize({ width, height: 844 });
        await scan(page, work.dashboardApp, async () => {
          await expect(page.getByRole("tab", { name: /^(Resultat|Results)$/ })).toBeVisible();
        });
        await scan(page, work.dashboardResult, async () => {
          await expect(page.getByText("Ditt resultat genereras.")).toBeVisible();
          await expect(
            page.getByRole("link", { name: "Ny körning" }).filter({ visible: true })
          ).toHaveAttribute("href", work.dashboardApp);
        });
      }
    });

    test("space overview, members and settings", { tag: "@vite" }, async ({ page }) => {
      const name = uniqueName(`E2E Space Shell ${colorScheme}`);
      const space = await createSpace(page, name);
      await scan(page, `${space}/overview`, async () => {
        await expect(page.getByRole("heading", { level: 1, name })).toBeVisible();
        await expect(page).toHaveTitle(`${name} · Eneo`);
      });
      for (const [tab, title] of [
        ["members", "Medlemmar"],
        ["settings", "Inställningar"]
      ]) {
        await scan(page, `${space}/${tab}`, async () => {
          await expect(
            page.getByRole("heading", { level: 2, name: title, exact: true })
          ).toBeVisible();
          await expect(page).toHaveTitle(`${title} · ${name} · Eneo`);
        });
      }
    });

    test(
      "space overview, knowledge and websites, and the create-collection dialog",
      { tag: "@vite" },
      async ({ page }) => {
        const name = uniqueName(`E2E A11y Space ${colorScheme}`);
        const space = await createSpace(page, name);

        await scan(page, `${space}/overview`, async () => {
          await expect(page.getByRole("heading", { level: 1, name })).toBeVisible();
        });
        await scan(page, `${space}/knowledge`, async () => {
          await expect(
            page.getByRole("heading", { level: 2, name: /^(Kunskap|Knowledge)$/ })
          ).toBeVisible();
        });
        await scan(page, `${space}/knowledge?tab=websites`, async () => {
          await expect(
            page.getByRole("tab", { name: /^(Webbplatser|Websites)$/, selected: true })
          ).toBeVisible();
          const panel = page.getByRole("tabpanel");
          // A new space has no websites: the empty state (a list shows a table).
          await expect(
            panel.getByRole("heading", { level: 3 }).or(panel.getByRole("table")).first()
          ).toBeVisible();
        });

        await page.goto(`${space}/knowledge`);
        await openCreateCollectionDialog(page);
        await expectNoAxeViolations(page);
      }
    );

    test(
      "organization Skills: create, saved detail and catalogue",
      { tag: "@vite" },
      async ({ page }) => {
        const name = uniqueName(`Organization Skill ${colorScheme}`);
        await page.goto("/spaces/organization/skills");
        await page.getByRole("link", { name: /^(Skapa skill|Create skill)$/i }).click();
        await expect(page).toHaveURL(/\/spaces\/organization\/skills\/new$/);
        await expect(
          page.getByRole("textbox", { name: /^(Instruktioner|Instructions)$/ })
        ).toBeVisible();
        await expectNoAxeViolations(page);
        await page.getByRole("textbox", { name: /^(Namn|Name)$/ }).fill(name);
        await page
          .getByRole("textbox", { name: /^(Beskrivning|Description)$/ })
          .fill("A report writing guide.");
        await page.context().grantPermissions(["clipboard-read", "clipboard-write"]);
        await page.evaluate(() =>
          navigator.clipboard.writeText("Write clearly and check the report's facts.")
        );
        await page.getByRole("textbox", { name: /^(Instruktioner|Instructions)$/ }).focus();
        await page.keyboard.press("ControlOrMeta+V");
        await page.getByRole("button", { name: /^(Skapa skill|Create skill)$/i }).click();
        await page.waitForURL(/\/spaces\/organization\/skills\/[\da-f-]+$/);
        await expect(page.getByRole("heading", { level: 1, name })).toBeVisible();
        await expectNoAxeViolations(page);
        await page.reload();
        await expect(page.getByRole("textbox", { name: /^(Namn|Name)$/ })).toHaveValue(name);
        await page
          .getByLabel(/^(Ytans innehåll|Space sections)$/)
          .getByRole("link", { name: "Skills", exact: true })
          .click();
        await expect(page).toHaveURL(/\/spaces\/organization\/skills$/);
        await expect(page.getByRole("link", { name, exact: true })).toBeVisible();
        await expectNoAxeViolations(page);
      }
    );

    test(
      "Skills: create, saved detail and a long reference preview",
      { tag: "@vite" },
      async ({ page }) => {
        test.setTimeout(90_000);
        const name =
          `${uniqueName(`E2E A11y Skill ${colorScheme}`)} ${"Detailed communication guide ".repeat(8)}`.slice(
            0,
            200
          );
        const description = "A writing guide with detailed editorial requirements. ".repeat(18);
        const instructions =
          "# Writing guide\n\nWrite clearly. Check facts and explain unfamiliar words.\n\n".repeat(
            300
          );

        await page.goto("/spaces/personal/skills/new");
        await expect(
          page.getByRole("textbox", { name: /^(Instruktioner|Instructions)$/ })
        ).toBeVisible();
        await expectNoAxeViolations(page);
        await page.getByRole("textbox", { name: /^(Namn|Name)$/ }).fill(name);
        if (process.env.E2E_BASE_URL) {
          await page
            .getByLabel(/^(Ytans innehåll|Space sections)$/)
            .getByRole("link", { name: "Skills", exact: true })
            .click();
          const leave = page.getByRole("alertdialog", { name: "Lämna sidan?" });
          await expect(leave).toBeVisible();
          await expectNoAxeViolations(page);
          await leave.getByRole("button", { name: "Avbryt", exact: true }).click();
          await expect(leave).not.toBeVisible();
        }
        await page.getByRole("textbox", { name: /^(Beskrivning|Description)$/ }).fill(description);
        await page.context().grantPermissions(["clipboard-read", "clipboard-write"]);
        await page.evaluate((text) => navigator.clipboard.writeText(text), instructions);
        const editor = page.getByRole("textbox", { name: /^(Instruktioner|Instructions)$/ });
        await editor.focus();
        await page.keyboard.press("ControlOrMeta+V");
        await expect(editor).toHaveText(instructions);
        await page.getByRole("button", { name: /^(Skapa skill|Create skill)$/i }).click();
        await page.waitForURL(/\/spaces\/personal\/skills\/[\da-f-]+$/);
        await expect(page.getByRole("heading", { level: 1, name })).toBeVisible();
        await expectNoAxeViolations(page);

        await page.goto("/spaces/personal/skills");
        await expect(page.getByRole("link", { name, exact: true })).toBeVisible();
        await expectNoAxeViolations(page);

        await page.goto("/spaces/personal/skills/new");
        await page.getByRole("button", { name: /^(Infoga referens|Insert reference)$/ }).click();
        const dialog = page.getByRole("dialog", { name: /^(Infoga referens|Insert reference)$/ });
        await dialog.getByRole("textbox").fill(name);
        await dialog.getByRole("button", { name: new RegExp(name) }).click();
        await expect(dialog.getByRole("heading", { name })).toBeVisible();
        await dialog.locator("summary", { hasText: /^(Beskrivning|Description)$/ }).click();
        await expect(dialog.getByText(description, { exact: true })).toBeVisible();
        const insert = dialog.getByRole("button", { name: /^(Infoga referens|Insert reference)$/ });
        await expect(dialog.getByText(instructions, { exact: true })).toBeVisible();
        await expect(insert).toBeEnabled();
        await expectNoAxeViolations(page);

        const header = dialog.getByRole("heading", { name });
        const before = { header: await header.boundingBox(), insert: await insert.boundingBox() };
        await dialog
          .locator("summary", { hasText: /^(Tekniska detaljer|Technical details)$/ })
          .focus();
        await expect(insert).toBeInViewport();
        expect(await header.boundingBox()).toEqual(before.header);
        expect(await insert.boundingBox()).toEqual(before.insert);

        // CSS viewport equivalents of desktop zoom, followed by narrow reflow.
        for (const viewport of [
          { width: 640, height: 400 },
          { width: 320, height: 200 },
          { width: 320, height: 800 }
        ]) {
          await page.setViewportSize(viewport);
          const instructionsHeading = dialog.getByRole("heading", {
            name: /^(Instruktioner|Instructions)$/
          });
          const readingArea = await instructionsHeading.evaluate((element) => {
            let scrollArea = element.parentElement;
            while (scrollArea && getComputedStyle(scrollArea).overflowY !== "auto") {
              scrollArea = scrollArea.parentElement;
            }
            if (!scrollArea) throw new Error("Missing scroll area for reference instructions");
            const style = getComputedStyle(scrollArea);
            return {
              height:
                scrollArea.clientHeight -
                parseFloat(style.paddingTop) -
                parseFloat(style.paddingBottom),
              lineHeight: parseFloat(getComputedStyle(element).lineHeight)
            };
          });
          expect(readingArea.height).toBeGreaterThanOrEqual(readingArea.lineHeight);
          await instructionsHeading.scrollIntoViewIfNeeded();
          await expect(instructionsHeading).toBeInViewport();
          await dialog
            .locator("summary", { hasText: /^(Tekniska detaljer|Technical details)$/ })
            .focus();
          await insert.focus();
          await expect(insert).toBeInViewport();
          expect(
            await dialog.evaluate((element) => element.scrollWidth > element.clientWidth)
          ).toBe(false);
        }
        await page.keyboard.press("Escape");
        await expect(dialog).not.toBeVisible();
        await expect(
          page.getByRole("textbox", { name: /^(Instruktioner|Instructions)$/ })
        ).toBeFocused();
      }
    );

    test("website detail and indexed content", { tag: "@vite" }, async ({ page }) => {
      await page.goto("/spaces/list");
      const spaceId = await apiPost(page, "/spaces/", {
        name: uniqueName(`E2E Website ${colorScheme}`)
      });
      const websiteId = await apiPost(page, `/spaces/${spaceId}/knowledge/websites/`, {
        url: "https://example.org/e2e",
        name: "E2E webbplats",
        crawl_type: "crawl",
        update_interval: "never",
        download_files: false
      });
      await scan(page, `/spaces/${spaceId}/knowledge/websites/${websiteId}`, async () => {
        await expect(page.getByRole("heading", { level: 1, name: "E2E webbplats" })).toBeVisible();
        await expect(page.getByRole("tabpanel", { name: "Indexeringar" })).toBeVisible();
      });
      await page.getByRole("tab", { name: "Indexerat innehåll" }).click();
      await expect(page.getByRole("tabpanel", { name: "Indexerat innehåll" })).toBeVisible();
      await expectNoAxeViolations(page);
    });

    test(
      "space flows, the new-flow dialog and a flow's page",
      { tag: "@vite" },
      async ({ page }) => {
        const space = await createSpace(page, uniqueName(`E2E A11y Flows ${colorScheme}`));
        await page.goto(`${space}/overview`);
        // A loading tab or its item count must not be mistaken for a disabled feature.
        const settings = await apiRequest<Schema<"SettingsPublic">>(page, "/settings/");
        test.skip(
          settings.flows_enabled !== true,
          "The tenant's flows_core gate is off in this stack, so the flow routes 404."
        );
        await expect(page.getByRole("link", { name: /^(Flöden|Flows)( \(\d+\))?$/ })).toBeVisible();

        await scan(page, `${space}/flows`, async () => {
          await expect(
            page.getByRole("heading", { level: 2, name: /^(Flöden|Flows)$/ })
          ).toBeVisible();
        });

        await page
          .getByRole("main")
          .getByRole("button", { name: /^(Nytt flöde|New flow)$/ })
          .first()
          .click();
        const dialog = page.getByRole("dialog", { name: /^(Nytt flöde|New flow)$/ });
        await expect(dialog.getByLabel(/^(namn|name)/i)).toBeVisible();
        await expectNoAxeViolations(page);

        const name = uniqueName("E2E A11y flöde");
        await dialog.getByLabel(/^(namn|name)/i).fill(name);
        await dialog.getByRole("button", { name: /^(skapa flöde|create flow)$/i }).click();
        await page.waitForURL(/\/flows\/[^/?]+$/, { timeout: 15_000 });
        await expect(page.getByRole("heading", { level: 1, name })).toBeVisible();
        await expect(page.getByRole("heading", { level: 2, name: /^(Steg|Steps)$/ })).toBeVisible();
        // The chat panel has settled: its composer (a combobox, as it offers
        // references on "@"), or why the chat is not available.
        await expect(
          page
            .getByRole("combobox", { name: /^(Fråga Flödesassistenten|Ask Flow assistant)$/ })
            .or(page.getByText(/^(Chatten är inte tillgänglig|The chat is not available)$/))
            .or(page.getByText(/^(Chatten kunde inte öppnas|The chat could not be opened)$/))
            .first()
        ).toBeVisible({ timeout: 15_000 });
        await expectNoAxeViolations(page);
      }
    );

    test("collection detail", { tag: "@vite" }, async ({ page }) => {
      // A new space gets the organisation's embedding model (e2e/seed.py),
      // which a collection needs.
      const space = await createSpace(page, uniqueName(`E2E A11y Collection ${colorScheme}`));
      await page.goto(`${space}/knowledge`);
      const dialog = await openCreateCollectionDialog(page);

      const name = uniqueName("E2E A11y samling");
      await dialog.getByLabel(/^(namn|name)$/i).fill(name);
      await dialog.getByRole("button", { name: /^(skapa samling|create collection)$/i }).click();
      await page.waitForURL(/\/knowledge\/collections\/[^/?]+$/, { timeout: 15_000 });
      await expect(page.getByRole("heading", { level: 1, name })).toBeVisible();
      await expectNoAxeViolations(page);
    });

    test("admin overview", { tag: "@vite" }, async ({ page }) => {
      await scan(page, "/admin", async () => {
        await expect(
          page.getByRole("heading", { level: 1, name: /^(Översikt|Overview)$/ })
        ).toBeVisible();
        // The cards have loaded: each is a region named by its heading, with its page's link.
        const users = page.getByRole("region", { name: /^(Aktiva användare|Active users)$/ });
        await expect(users).toBeVisible();
        await expect(
          users.getByRole("link", { name: /^(Visa användare|View users)$/ })
        ).toBeVisible();
        await expect(page.getByRole("region", { name: /^Crawler$/ })).toBeVisible();
      });
    });

    test("admin settings", { tag: "@vite" }, async ({ page }) => {
      await scan(page, "/admin/settings", async () => {
        await expect(
          page.getByRole("heading", { level: 1, name: /^(Inställningar|Settings)$/ })
        ).toBeVisible();
        await expect(page.getByRole("switch").first()).toBeVisible();
      });
    });

    test("admin users", { tag: "@vite" }, async ({ page }) => {
      await scan(page, "/admin/users", async () => {
        await expect(
          page.getByRole("heading", { level: 1, name: /^(Användare|Users)$/ })
        ).toBeVisible();
        await expect(page.getByRole("main").getByText(/^\d+ (användare|users?)$/)).toBeVisible();
      });
    });

    test("admin user groups", { tag: "@vite" }, async ({ page }) => {
      test.skip(!process.env.E2E_BASE_URL, "User-group administration has a Vite-only route.");
      await scan(page, "/admin/user-groups", async () => {
        await expect(
          page.getByRole("heading", { level: 1, name: /^(Användargrupper|User Groups)$/ })
        ).toBeVisible();
        await expect(page).toHaveTitle(/^(Användargrupper|User Groups) · Eneo$/);
        const create = page
          .getByRole("button", { name: /^(Skapa användargrupp|Create user group)$/ })
          .first();
        await create.focus();
        await page.keyboard.press("Enter");
        const dialog = page.getByRole("dialog", {
          name: /^(Skapa en ny användargrupp|Create a new user group)$/
        });
        await expect(dialog).toBeVisible();
        await expect(dialog.getByRole("textbox", { name: /Gruppnamn|Group name/ })).toBeVisible();
        await expectNoAxeViolations(page);
        await page.keyboard.press("Escape");
        await expect(dialog).toBeHidden();
        await expect(create).toBeFocused();
      });
    });

    test("admin federation", { tag: "@vite" }, async ({ page }) => {
      test.skip(!process.env.E2E_BASE_URL, "Federation administration has a Vite-only route.");
      // A configured IdP is a UI fixture; this scan never contacts an IdP or saves credentials.
      await page.route("**/api/v1/runtime-config", async (route) => {
        const response = await route.fetch();
        await route.fulfill({
          response,
          json: { ...(await response.json()), federation_enabled: true }
        });
      });
      const view: FederationView = {
        configured: true,
        provider: "Example IdP",
        discovery_endpoint: "https://idp.example/.well-known/openid-configuration",
        issuer: "https://idp.example",
        client_id: "e2e-client",
        client_secret_set: true,
        encryption_status: "encrypted",
        allowed_domains: ["example.org"],
        redirect_uris: ["https://eneo.example/login/callback"],
        scopes: ["openid", "email", "profile"],
        token_endpoint_auth_method: "client_secret_post",
        revision: "e2e-revision"
      };
      await page.route("**/api/v1/admin/federation", (route) =>
        route.fulfill({ headers: sessionResponseHeaders(route), json: view })
      );
      await scan(page, "/admin/federation", async () => {
        await expect(
          page.getByRole("heading", { level: 1, name: "Inloggning (SSO)" })
        ).toBeVisible();
        await expect(page.getByRole("textbox", { name: /^Klient-ID\b/ })).toHaveValue("e2e-client");
        await expect(
          page.getByRole("link", { name: "Inloggning (SSO)", exact: true })
        ).toBeVisible();
        await expect(page).toHaveTitle("Inloggning (SSO) · Eneo");
      });
    });

    test("admin models", { tag: "@vite" }, async ({ page }) => {
      await scan(page, "/admin/models", async () => {
        await expect(page.getByRole("tab", { name: /migreringshistorik/i })).toBeVisible();
        // The seeded provider's model table (e2e/seed.py).
        await expect(page.getByRole("main").getByRole("table").first()).toBeVisible();
      });
    });

    test("admin integrations", { tag: "@vite" }, async ({ page }) => {
      await scan(page, "/admin/integrations", async () => {
        await expect(
          page.getByRole("heading", { level: 1, name: /^(Integrationer|Integrations)$/ })
        ).toBeVisible();
        // The providers have loaded.
        await expect(page.locator('[data-tour="admin-integrations"]')).toBeVisible();
      });
    });

    test("admin crawler", { tag: "@vite" }, async ({ page }) => {
      await scan(page, "/admin/crawler", async () => {
        await expect(page.getByRole("heading", { level: 1, name: /^Crawler$/ })).toBeVisible();
        await expect(page.getByRole("group", { name: /schemaläggare|scheduler/i })).toBeVisible();
        await expect(page.getByRole("tab", { name: /^(schema|schedule)$/i })).toBeVisible();
      });
    });

    test("admin flow settings", async ({ page }) => {
      await page.goto("/admin");
      const flowsLink = page
        .getByRole("navigation", { name: /^Administration$/ })
        .getByRole("link", { name: /^(Flöden|Flows)$/ });
      test.skip(
        (await flowsLink.count()) === 0,
        "The tenant's flows_core gate is off in this stack, so /admin/flow-settings 404s."
      );

      await scan(page, "/admin/flow-settings", async () => {
        await expect(
          page.getByRole("heading", { level: 1, name: /^(Flöden|Flows)$/ })
        ).toBeVisible();
        await expect(
          page.getByRole("switch", {
            name: /^(Tillåt nya steg som körs per fil|Allow new steps that run once per file)/
          })
        ).toBeVisible();
      });
    });

    test("account", { tag: "@vite" }, async ({ page }) => {
      await scan(page, "/account", async () => {
        await expect(page.getByText(/byt lösenord/i).first()).toBeVisible();
      });
    });

    // Touch layouts: a phone, and an iPad upright and sideways. All report a
    // coarse pointer, so the 44 px touch targets apply; below 1024 px (the
    // phone, the iPad upright) the top bar or the chat's own header replaces
    // the SideNav.
    for (const layout of TOUCH_LAYOUTS) {
      test.describe(layout.name, () => {
        test.use({ viewport: layout.viewport, hasTouch: true, isMobile: true });

        test("a touch pointer", async ({ page }) => {
          await spacesList(page);
          expect(await page.evaluate(() => matchMedia("(pointer: coarse)").matches)).toBe(true);
        });

        test("personal chat", { tag: "@vite" }, async ({ page }) => {
          await scan(page, "/spaces/personal/chat", () => chatStartReady(page));
        });

        if (layout.phone) {
          test("offline: the banner, and a question kept with the reason", async ({
            page,
            context
          }) => {
            await page.goto("/spaces/personal/chat");
            await chatStartReady(page);
            await context.setOffline(true);
            // One banner, under the chat's own header (the shell's gives way).
            const banners = page.getByRole("main").getByText(/^(Du är offline|You're offline)$/);
            const banner = banners.filter({ visible: true });
            await expect(banner).toHaveCount(1);
            const header = page.locator("[data-own-mobile-header]");
            expect((await banner.boundingBox())!.y).toBeGreaterThan(
              (await header.boundingBox())!.y + (await header.boundingBox())!.height - 1
            );

            await chatComposer(page).fill("Vilken gräns gäller?");
            await chatComposer(page).press("ControlOrMeta+Enter");
            await expect(chatComposer(page)).toHaveValue("Vilken gräns gäller?");
            await expect(chatComposer(page)).toHaveAccessibleDescription(
              /^(Du är offline\. Skicka frågan|You're offline\. Send the question)/
            );
            await expectNoAxeViolations(page);

            await context.setOffline(false);
            await expect(banner).toBeHidden();
          });

          test("chat: an answer, and its activity sheet", async ({ page }) => {
            await addActivityToAnswers(page);
            await answeredQuestion(page);
            await expectNoAxeViolations(page);

            await activityPill(page).click();
            const sheet = page.getByRole("dialog", { name: ACTIVITY_PANEL });
            await expect(sheet.getByRole("tabpanel", { name: /^(Steg|Steps)$/ })).toBeVisible();
            await expectNoAxeViolations(page);
          });
        }

        test("spaces list", { tag: "@vite" }, async ({ page }) => {
          await scan(page, "/spaces/list", async () => {
            await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
          });
        });

        test("a space, and the organisation space", { tag: "@vite" }, async ({ page }) => {
          const name = uniqueName(`E2E A11y Touch Space ${colorScheme}`);
          const space = await createSpace(page, name);
          await scan(page, `${space}/overview`, async () => {
            await expect(page.getByRole("heading", { level: 1, name })).toBeVisible();
            // A phone lists what manages the space; tablets keep a tab for each.
            await expect(
              page.getByRole("region", { name: /^(Hantera ytan|Manage space)$/ })
            ).toHaveCount(layout.phone ? 1 : 0);
          });
          await scan(page, "/spaces/organization/knowledge", async () => {
            await expect(
              page.getByRole("heading", { level: 1, name: /^(Organisation|Organization)$/ })
            ).toBeVisible();
          });
        });

        if (layout.drawer) {
          test("the navigation drawer open", async ({ page }) => {
            await spacesList(page);
            await page.getByRole("button", { name: /öppna menyn|open menu/i }).click();
            const drawer = page.getByRole("dialog", { name: /^(Meny|Menu)$/ });
            await expect(
              drawer.getByRole("navigation", { name: /huvudmeny|main menu/i })
            ).toBeVisible();
            // The profile opens Konto, not a menu on the drawer (decision 22).
            await expect(
              drawer.getByRole("link", {
                name: /: (konto och inställningar|account and settings)$/
              })
            ).toHaveAttribute("href", "/account");
            await expectNoAxeViolations(page);
          });
        }

        test("account", { tag: "@vite" }, async ({ page }) => {
          // Where the drawer is, Konto is a page (decision 22); sideways,
          // "Mitt konto" and its tabs.
          await scan(page, "/account", async () => {
            await expect(
              page.getByRole("heading", {
                level: 1,
                name: layout.drawer ? /^(Konto|Account)$/ : /^(Mitt konto|My account)$/
              })
            ).toBeVisible();
          });
          await scan(page, "/account/appearance", async () => {
            await expect(page.getByRole("radiogroup", { name: /^(Tema|Theme)$/ })).toBeVisible();
          });
        });

        test("the command palette open", async ({ page }) => {
          await spacesList(page);
          await openPalette(page);
          await expectNoAxeViolations(page);
        });

        test("admin users", { tag: "@vite" }, async ({ page }) => {
          await scan(page, "/admin/users", async () => {
            await expect(
              page.getByRole("heading", { level: 1, name: /^(Användare|Users)$/ })
            ).toBeVisible();
            await expect(
              page.getByRole("main").getByText(/^\d+ (användare|users?)$/)
            ).toBeVisible();
          });
        });

        test("admin overview and models", { tag: "@vite" }, async ({ page }) => {
          await scan(page, "/admin", async () => {
            await expect(
              page.getByRole("heading", { level: 1, name: /^(Översikt|Overview)$/ })
            ).toBeVisible();
          });
          await scan(page, "/admin/models", async () => {
            await expect(
              page.getByRole("heading", { level: 2, name: "E2E Mock Provider" })
            ).toBeVisible();
          });
        });

        // A phone only: each scan opens an access session, and the backend
        // allows five an hour (admin-audit.spec.ts opens one more).
        if (layout.phone) {
          test("admin audit log", { tag: "@vite" }, async ({ page }) => {
            await auditLogs(page);
            await expectNoAxeViolations(page);
          });
        }

        test(
          "a space's assistants, apps and members, an editor and an app result",
          { tag: "@vite" },
          async ({ page }) => {
            const work = await spaceWithWork(
              page,
              uniqueName(`E2E A11y Touch Work ${colorScheme}`)
            );
            for (const [tab, name] of [
              ["assistants", /^(Assistenter|Assistants)$/],
              ["apps", /^(Appar|Apps)$/],
              ["members", /^(Medlemmar|Members)$/]
            ] as const) {
              await scan(page, `${work.space}/${tab}`, async () => {
                await expect(page.getByRole("heading", { level: 2, name })).toBeVisible();
              });
            }
            // A phone opens the editor on its index of sections (decision 21).
            for (const editor of layout.phone
              ? [work.editor, `${work.editor}?section=instructions`]
              : [work.editor]) {
              await scan(page, editor, async () => {
                await expect(
                  page.getByRole("heading", { level: 1, name: /^Bygglov / })
                ).toBeVisible();
              });
            }
            await scan(page, work.result, async () => {
              await expect(
                page.getByRole("heading", { level: 1, name: /^(Indata|Input): / })
              ).toBeVisible();
              await expect(
                page.getByText(/^(Ditt resultat genereras\.|Your result is being generated\.)$/)
              ).toBeVisible();
              await expect(page.locator("[data-result-skeleton]")).toHaveAttribute(
                "aria-hidden",
                "true"
              );
            });
          }
        );

        test(
          "space app pages, group-chat editor and service pages",
          { tag: "@vite" },
          async ({ page }) => {
            const work = await spaceWithWork(
              page,
              uniqueName(`E2E Resource Routes ${colorScheme}`)
            );
            const groupName = uniqueName("E2E Grupp");
            const group = await apiPost(page, `${work.space}/applications/group-chats/`, {
              name: groupName
            });
            const serviceName = uniqueName("E2E Service");
            const service = await apiPost(page, `${work.space}/applications/services/`, {
              name: serviceName
            });
            await scan(page, work.app, async () => {
              await expect(page.getByRole("tab", { name: /^(Resultat|Results)$/ })).toBeVisible();
              await expect(page.getByRole("link", { name: /^(Redigera|Edit)$/ })).toHaveAttribute(
                "href",
                work.appEditor
              );
            });
            for (const editor of layout.phone
              ? [work.appEditor, `${work.appEditor}?section=instructions`]
              : [work.appEditor]) {
              await scan(page, editor, async () => {
                await expect(
                  page.getByRole("heading", { level: 1, name: /^Protokoll / })
                ).toBeVisible();
              });
            }
            await scan(page, `${work.space}/group-chats/${group}/edit`, async () => {
              await expect(page.getByRole("heading", { level: 1, name: groupName })).toBeVisible();
            });
            await scan(page, `${work.space}/services`, async () => {
              await expect(
                page.getByRole("heading", { level: 2, name: /^(Tjänster|Services)$/ })
              ).toBeVisible();
            });
            for (const tab of ["playground", "settings"]) {
              await scan(page, `${work.space}/services/${service}?tab=${tab}`, async () => {
                await expect(
                  page.getByRole("heading", { level: 1, name: serviceName })
                ).toBeVisible();
                await expect(
                  page.getByRole("tab", {
                    name:
                      tab === "settings"
                        ? /^(Inställningar|Settings)$/
                        : /^(Testområde|Playground)$/
                  })
                ).toHaveAttribute("aria-selected", "true");
              });
            }
          }
        );

        test("Konto's pages", { tag: "@vite" }, async ({ page }) => {
          for (const [path, title] of [
            ["/account/password", /^(Byt lösenord|Change password)$/],
            ["/account/copy-format", /^(Kopieringsformat|Copy format)$/],
            ["/account/api-keys", /^(Mina API-nycklar|My API keys)$/],
            ["/account/integrations", /^(Integrationer|Integrations)$/]
          ] as const) {
            await scan(page, path, async () => {
              // Below 1024 px the page's own heading; sideways, "Mitt konto".
              await expect(
                page.getByRole("heading", {
                  level: 1,
                  name: layout.drawer ? title : /^(Mitt konto|My account)$/
                })
              ).toBeAttached();
            });
          }
        });

        test("Nyheter", { tag: "@vite" }, async ({ page }) => {
          await scan(page, "/whats-new", async () => {
            await expect(
              page.getByRole("heading", { level: 1, name: /^(Nyheter|What's new)$/ })
            ).toBeVisible();
          });
        });
      });
    }
  });
}

// Reflow at 320 px with a mouse: what a desktop user gets at 400 % zoom.
test.describe("reflow at 320 px (1.4.10)", () => {
  test.use({ viewport: { width: 320, height: 640 }, contextOptions: { reducedMotion: "reduce" } });

  test("personal chat", { tag: "@vite" }, async ({ page }) => {
    await page.goto("/spaces/personal/chat");
    await chatStartReady(page);
    await expectNoSidewaysPageScroll(page);
  });

  test("spaces list", { tag: "@vite" }, async ({ page }) => {
    await spacesList(page);
    await expectNoSidewaysPageScroll(page);
  });

  test("space overview and knowledge", { tag: "@vite" }, async ({ page }) => {
    const name = uniqueName("E2E Reflow Space");
    const space = await createSpace(page, name);

    await page.goto(`${space}/overview`);
    await expect(page.getByRole("heading", { level: 1, name })).toBeVisible();
    await expectNoSidewaysPageScroll(page);

    await page.goto(`${space}/knowledge`);
    await expect(
      page.getByRole("heading", { level: 2, name: /^(Kunskap|Knowledge)$/ })
    ).toBeVisible();
    await expectNoSidewaysPageScroll(page);
  });

  test("admin users", { tag: "@vite" }, async ({ page }) => {
    await page.goto("/admin/users");
    await expect(
      page.getByRole("heading", { level: 1, name: /^(Användare|Users)$/ })
    ).toBeVisible();
    await expect(page.getByRole("main").getByText(/^\d+ (användare|users?)$/)).toBeVisible();
    await expectNoSidewaysPageScroll(page);
  });

  test("admin models", { tag: "@vite" }, async ({ page }) => {
    await page.goto("/admin/models");
    await expect(page.getByRole("tab", { name: /migreringshistorik/i })).toBeVisible();
    // A phone lists a provider's models as rows (decision 31).
    await expect(page.getByRole("main").getByRole("list").first()).toBeVisible();
    await expectNoSidewaysPageScroll(page);
  });

  test("account", { tag: "@vite" }, async ({ page }) => {
    await page.goto("/account");
    await expect(page.getByText(/byt lösenord/i).first()).toBeVisible();
    await expectNoSidewaysPageScroll(page);
    for (const path of [
      "/account/appearance",
      "/account/copy-format",
      "/account/password",
      "/account/api-keys",
      "/account/integrations"
    ]) {
      await page.goto(path);
      await expect(
        page.getByRole("link", { name: /^(Tillbaka till|Back to) Konto$/ })
      ).toBeVisible();
      await expectNoSidewaysPageScroll(page);
    }
  });

  test("Nyheter", { tag: "@vite" }, async ({ page }) => {
    await page.goto("/whats-new");
    await expect(page.getByRole("link", { name: /^(Tillbaka till|Back to) Konto$/ })).toBeVisible();
    await expectNoSidewaysPageScroll(page);
  });

  test(
    "a space's assistants, apps and members, an editor and an app result",
    { tag: "@vite" },
    async ({ page }) => {
      const work = await spaceWithWork(page, uniqueName("E2E Reflow Work"));
      for (const tab of ["assistants", "apps", "members"]) {
        await page.goto(`${work.space}/${tab}`);
        await expect(page.getByRole("heading", { level: 2 }).first()).toBeVisible();
        await expectNoSidewaysPageScroll(page);
      }
      for (const editor of [work.editor, `${work.editor}?section=instructions`]) {
        await page.goto(editor);
        await expect(page.getByRole("heading", { level: 1, name: /^Bygglov / })).toBeVisible();
        await expectNoSidewaysPageScroll(page);
      }
      await page.goto(work.result);
      await expect(
        page.getByRole("heading", { level: 1, name: /^(Indata|Input): / })
      ).toBeVisible();
      await expectNoSidewaysPageScroll(page);
    }
  );
});

// Focus not obscured (2.4.11): errors and warnings stay until closed, at the
// bottom edge where the chat docks its composer; the toasts rise out of the way
// of what has focus (src/components/ui/toast-lift.ts).
test.describe("toasts never cover the focused element (2.4.11)", () => {
  for (const [layout, options] of [
    ["desktop (1280 × 800)", { viewport: { width: 1280, height: 800 } }],
    ["phone (390 × 844)", { viewport: { width: 390, height: 844 }, hasTouch: true, isMobile: true }]
  ] as const) {
    test.describe(layout, () => {
      test.use({ ...options, contextOptions: { reducedMotion: "reduce" } });

      test("an error toast over the docked chat composer", async ({ page }) => {
        await answeredQuestion(page);
        // A file type the chat does not take: an error that stays until closed.
        await page.locator('input[type="file"]').setInputFiles({
          name: "rapport.exe",
          mimeType: "application/x-msdownload",
          buffer: Buffer.from("MZ")
        });
        await expect(page.getByText(/^rapport\.exe: /)).toBeVisible();

        await chatComposer(page).fill("Och nästa fråga?");
        await expectFocusClearOfToasts(page);
        // Through the composer's controls to Send.
        const send = page.getByRole("button", { name: /skicka meddelande|send message/i });
        for (let stop = 0; stop < 10; stop += 1) {
          if (await send.evaluate((button) => button === document.activeElement)) break;
          await page.keyboard.press("Tab");
          await expectFocusClearOfToasts(page);
        }
        await expect(send).toBeFocused();
      });
    });
  }
});

test(
  "the skip link is the first tab stop and moves focus to the main content",
  { tag: "@vite" },
  async ({ page }) => {
    await page.goto("/spaces/list");
    await expect(page.getByRole("heading", { level: 1 })).toBeVisible();

    await page.keyboard.press("Tab");
    const skipLink = page.getByRole("link", { name: /hoppa till innehåll|skip to content/i });
    await expect(skipLink).toBeFocused();
    // Visually hidden until focused (sr-only, a 1px clip): with focus it must be
    // shown at full size (2.4.7) and be a real target (2.5.8).
    const box = await skipLink.boundingBox();
    expect(box?.width ?? 0).toBeGreaterThanOrEqual(24);
    expect(box?.height ?? 0).toBeGreaterThanOrEqual(24);

    await page.keyboard.press("Enter");
    await expect(page.locator("#main-content")).toBeFocused();
  }
);
