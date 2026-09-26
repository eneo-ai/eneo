import AxeBuilder from "@axe-core/playwright";
import type { Page } from "@playwright/test";
import { SIDE_NAV_COLLAPSED_COOKIE } from "../src/components/shell/side-nav-preference";
import { assertDocumented, WCAG_22_AA_TAGS } from "../src/test/wcag";
import { expect, test } from "./csp";
import {
  activityPill,
  addActivityToAnswers,
  askChatQuestion,
  chatComposer,
  conversationLog,
  createSpace,
  MOCK_REPLY,
  openCreateCollectionDialog,
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
const DEV_ONLY = ["nextjs-portal", ".tsqd-parent-container"];

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
  // LoadingState skeletons are aria-busy: scan what loaded, not a skeleton.
  await expect(page.locator('[aria-busy="true"]')).toHaveCount(0);

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

/** Opens a route, waits until it shows real content, then scans it. */
async function scan(page: Page, path: string, ready: () => Promise<void>, exceptions?: Exceptions) {
  await page.goto(path);
  await ready();
  await expectNoAxeViolations(page, exceptions);
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

    test("personal chat", async ({ page }) => {
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

    test("spaces list", async ({ page }) => {
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

    test("assistant catalogue (dashboard)", async ({ page }) => {
      await scan(page, "/dashboard", async () => {
        await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
      });
    });

    test("assistant catalogue with the SideNav collapsed to its icon rail", async ({
      page,
      baseURL
    }) => {
      await page
        .context()
        .addCookies([{ name: SIDE_NAV_COLLAPSED_COOKIE, value: "1", url: baseURL! }]);
      await scan(page, "/dashboard", async () => {
        await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
        await expect(
          page.getByRole("button", { name: /fäll ut sidomenyn|expand the side menu/i })
        ).toBeVisible();
      });
    });

    test("space overview, knowledge and websites, and the create-collection dialog", async ({
      page
    }) => {
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
    });

    test("collection detail", async ({ page }) => {
      const space = await createSpace(page, uniqueName(`E2E A11y Collection ${colorScheme}`));
      await page.goto(`${space}/knowledge`);
      const dialog = await openCreateCollectionDialog(page);
      test.skip(
        await dialog
          .getByText(/inga inbäddningsmodeller|not have any embedding models/i)
          .isVisible(),
        "A collection needs an embedding model in its space, and the e2e stack (e2e/seed.py) " +
          "seeds none; the scan runs once it does."
      );

      const name = uniqueName("E2E A11y samling");
      await dialog.getByLabel(/^(namn|name)$/i).fill(name);
      await dialog.getByRole("button", { name: /^(skapa samling|create collection)$/i }).click();
      await page.waitForURL(/\/knowledge\/collections\/[^/?]+$/, { timeout: 15_000 });
      await expect(page.getByRole("heading", { level: 1, name })).toBeVisible();
      await expectNoAxeViolations(page);
    });

    test("admin overview", async ({ page }) => {
      await scan(page, "/admin", async () => {
        await expect(page.getByRole("heading", { level: 1, name: /^Organisation$/ })).toBeVisible();
        await expect(page.getByRole("switch").first()).toBeVisible();
      });
    });

    test("admin users", async ({ page }) => {
      await scan(page, "/admin/users", async () => {
        await expect(
          page.getByRole("heading", { level: 1, name: /^(Användare|Users)$/ })
        ).toBeVisible();
        await expect(page.getByRole("main").getByText(/^\d+ (användare|users?)$/)).toBeVisible();
      });
    });

    test("admin models", async ({ page }) => {
      await scan(page, "/admin/models", async () => {
        await expect(page.getByRole("tab", { name: /migreringshistorik/i })).toBeVisible();
        // The seeded provider's model table (e2e/seed.py).
        await expect(page.getByRole("main").getByRole("table").first()).toBeVisible();
      });
    });

    test("account", async ({ page }) => {
      await scan(page, "/account", async () => {
        await expect(page.getByText(/byt lösenord/i).first()).toBeVisible();
      });
    });

    // Phone layouts: the top bar or the chat's own header instead of the
    // SideNav, and a touch pointer, so the 44 px touch targets apply.
    test.describe("phone (390 × 844)", () => {
      test.use({ viewport: { width: 390, height: 844 }, hasTouch: true, isMobile: true });

      test("personal chat", async ({ page }) => {
        await scan(page, "/spaces/personal/chat", () => chatStartReady(page));
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

      test("spaces list", async ({ page }) => {
        await scan(page, "/spaces/list", async () => {
          await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
        });
      });

      test("the navigation drawer open", async ({ page }) => {
        await spacesList(page);
        await page.getByRole("button", { name: /öppna menyn|open menu/i }).click();
        const drawer = page.getByRole("dialog", { name: /^(Meny|Menu)$/ });
        await expect(
          drawer.getByRole("navigation", { name: /huvudmeny|main menu/i })
        ).toBeVisible();
        await expectNoAxeViolations(page);
      });

      test("the command palette open", async ({ page }) => {
        await spacesList(page);
        await openPalette(page);
        await expectNoAxeViolations(page);
      });

      test("admin users", async ({ page }) => {
        await scan(page, "/admin/users", async () => {
          await expect(
            page.getByRole("heading", { level: 1, name: /^(Användare|Users)$/ })
          ).toBeVisible();
          await expect(page.getByRole("main").getByText(/^\d+ (användare|users?)$/)).toBeVisible();
        });
      });
    });
  });
}

test("the skip link is the first tab stop and moves focus to the main content", async ({
  page
}) => {
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
});
