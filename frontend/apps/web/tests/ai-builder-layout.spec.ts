import { expect, test, type APIRequestContext, type Page } from "@playwright/test";
import { backendFetch, expectOk } from "./helpers";

function makeFixtures(spaceId: string) {
  const draft = {
    session_id: "plan-session",
    space_id: spaceId,
    status: "awaiting_approval",
    target_kind: "create",
    flow_id: null,
    latest_plan_id: "plan-1",
    draft_title: "Sammanfatta till PDF",
    created_at: "2026-07-11T09:00:00Z",
    updated_at: "2026-07-11T09:05:00Z"
  };
  const session = {
    ...draft,
    conversation: [
      {
        message_id: "m-1",
        role: "user",
        content: "Sammanfatta rapporter till en PDF",
        timestamp: "2026-07-11T09:00:00Z"
      },
      {
        message_id: "m-2",
        role: "assistant",
        content: "Här är mitt förslag:",
        timestamp: "2026-07-11T09:05:00Z",
        requirements_summary: {
          requirements_version: "v1",
          summary: "Skapa en sammanfattning av inskickade rapporter som PDF.",
          key_decisions: [
            { topic: "Slutresultat", decision: "PDF-dokument" },
            { topic: "Omfattning", decision: "En sammanfattning per körning" }
          ],
          input_description: "Text vid körning",
          output_description: "PDF med samlad översikt",
          assumptions: ["Underlaget är på svenska."],
          manual_setup_notes: []
        }
      }
    ],
    latest_turn: null
  };
  return { draft, session };
}

const PLAN = {
  plan_id: "plan-1",
  status: "proposed",
  proposal: {
    spec: {
      flow_name: "Sammanfatta till PDF",
      flow_description:
        "Tar emot en text vid körning och levererar en sammanfattning som ett PDF-dokument.",
      steps: [],
      form_fields: null
    },
    plan_rationale:
      "Tre steg håller varje delmoment enkelt att kontrollera och ger ett förutsägbart resultat.",
    assumptions: [
      "Underlaget är på svenska.",
      "En sammanfattning per körning räcker.",
      "PDF-dokumentet behöver ingen särskild mall."
    ],
    lint_warnings: [],
    description_override_manual: false,
    edit: null
  }
};

async function personalSpaceId(page: Page, request: APIRequestContext): Promise<string> {
  const response = await backendFetch(page, request, "/api/v1/spaces/type/personal/");
  await expectOk(response, "loading personal space");
  const body = (await response.json()) as { id?: unknown };
  if (typeof body.id !== "string") throw new Error("personal space id missing");
  return body.id;
}

async function stubAiBuilderApi(page: Page, spaceId: string) {
  const { draft, session } = makeFixtures(spaceId);
  await page.route("**/api/v1/flows/ai-builder/**", async (route) => {
    const url = route.request().url();
    if (url.includes("/models")) {
      return route.fulfill({ json: { models: [], default_model_id: null } });
    }
    if (/\/plans\/plan-1\/?$/.test(url)) {
      return route.fulfill({ json: PLAN });
    }
    if (/\/sessions\/plan-session\/?$/.test(url)) {
      return route.fulfill({ json: session });
    }
    if (/\/sessions\/?(\?.*)?$/.test(url)) {
      return route.fulfill({ json: { sessions: [draft] } });
    }
    return route.fulfill({ json: {} });
  });
}

async function openPlanReview(page: Page, request: APIRequestContext) {
  await page.goto("/");
  const spaceId = await personalSpaceId(page, request);
  await stubAiBuilderApi(page, spaceId);
  await page.goto("/spaces/personal/flows/ai-builder");
  await expect(page.locator("#ai-builder-plan-pane")).toBeAttached({ timeout: 20_000 });
}

// Must track messages/sv.json `ai_builder_why_this_design`, which the plan pane
// renders for create-mode reviews (scoped step reviews use `..._why_this_change`).
const RATIONALE_TRIGGER = "Varför upplägget ser ut så här";

function layoutMetrics(page: Page) {
  return page.evaluate(() => {
    const containerEl = [...document.querySelectorAll("div")].find(
      (d) => getComputedStyle(d).containerName === "builder"
    );
    if (!containerEl) throw new Error("builder container not found");
    const inner = containerEl.firstElementChild as HTMLElement;
    const taskRegion = document.querySelector<HTMLElement>(
      '[role="region"][aria-label="Uppgiftspanel"]'
    );
    const planRegion = document.querySelector<HTMLElement>(
      '[role="region"][aria-label="Planförslag"]'
    );
    const stickyGroup = inner.querySelector<HTMLElement>("div.sticky");
    const compact = document.querySelector<HTMLElement>(".phase-compact");
    const phaseList = document.querySelector<HTMLElement>(".phase-list");
    return {
      containerWidth: containerEl.clientWidth,
      innerOverflowY: getComputedStyle(inner).overflowY,
      taskRegionOverflowY: taskRegion ? getComputedStyle(taskRegion).overflowY : null,
      planRegionOverflowY: planRegion ? getComputedStyle(planRegion).overflowY : null,
      stickyGroupPosition: stickyGroup ? getComputedStyle(stickyGroup).position : null,
      compactVisible: compact ? getComputedStyle(compact).display !== "none" : null,
      phaseListVisible: phaseList ? getComputedStyle(phaseList).display !== "none" : null
    };
  });
}

async function viewportForContainerWidth(page: Page, target: number): Promise<number> {
  const probe = 1400;
  await page.setViewportSize({ width: probe, height: 620 });
  const { containerWidth } = await layoutMetrics(page);
  return probe - containerWidth + target;
}

test.describe("AI Builder responsive accessibility", () => {
  test("split view keeps each pane independently scrollable", async ({ page, request }) => {
    await page.setViewportSize({ width: 1440, height: 620 });
    await openPlanReview(page, request);

    const m = await layoutMetrics(page);
    expect(m.containerWidth).toBeGreaterThanOrEqual(1040);
    expect(m.innerOverflowY).toBe("hidden");
    expect(m.taskRegionOverflowY).toBe("auto");
    expect(m.planRegionOverflowY).toBe("auto");
    expect(m.compactVisible).toBe(false);
    expect(m.phaseListVisible).toBe(true);

    await expect(page.getByRole("button", { name: "Uppgift", exact: true })).toBeHidden();
  });

  test("the rationale default follows the builder container width until the user touches it", async ({
    page,
    request
  }) => {
    await openPlanReview(page, request);
    const trigger = page.getByRole("button", { name: RATIONALE_TRIGGER });

    const wideViewport = await viewportForContainerWidth(page, 800);
    await page.setViewportSize({ width: wideViewport, height: 620 });
    await expect(trigger).toHaveAttribute("aria-expanded", "true");

    const narrowViewport = await viewportForContainerWidth(page, 740);
    expect(narrowViewport).toBeGreaterThan(768);
    await page.setViewportSize({ width: narrowViewport, height: 620 });
    await expect(trigger).toHaveAttribute("aria-expanded", "false");

    await trigger.click();
    await expect(trigger).toHaveAttribute("aria-expanded", "true");
    await page.setViewportSize({ width: wideViewport, height: 620 });
    await page.setViewportSize({ width: narrowViewport, height: 620 });
    await expect(trigger).toHaveAttribute("aria-expanded", "true");
  });

  test("tabs mode: phase group and action bar stay pinned while the page scrolls", async ({
    page,
    request
  }) => {
    await page.setViewportSize({ width: 900, height: 520 });
    await openPlanReview(page, request);

    const m = await layoutMetrics(page);
    expect(m.containerWidth).toBeLessThan(1040);
    expect(m.stickyGroupPosition).toBe("sticky");

    const pinned = await page.evaluate(() => {
      const containerEl = [...document.querySelectorAll("div")].find(
        (d) => getComputedStyle(d).containerName === "builder"
      );
      const inner = containerEl?.firstElementChild as HTMLElement;
      inner.scrollTop = inner.scrollHeight;
      const group = inner.querySelector<HTMLElement>("div.sticky");
      const actionBar = document
        .querySelector('[id="ai-builder-plan-pane"]')
        ?.querySelector<HTMLElement>("div.sticky.bottom-0");
      const innerRect = inner.getBoundingClientRect();
      return {
        scrolled: inner.scrollTop > 0,
        groupTopDelta: group ? Math.abs(group.getBoundingClientRect().top - innerRect.top) : null,
        actionBarPosition: actionBar ? getComputedStyle(actionBar).position : null,
        actionBarBottomDelta: actionBar
          ? Math.abs(actionBar.getBoundingClientRect().bottom - innerRect.bottom)
          : null
      };
    });
    expect(pinned.scrolled).toBe(true);
    expect(pinned.groupTopDelta ?? 99).toBeLessThanOrEqual(1);
    expect(pinned.actionBarPosition).toBe("sticky");
    expect(pinned.actionBarBottomDelta ?? 99).toBeLessThanOrEqual(1);
  });

  test("mobile: focused plan controls stay clear of the stacked action bar", async ({
    page,
    request
  }) => {
    await page.setViewportSize({ width: 390, height: 700 });
    await openPlanReview(page, request);

    const clearance = await page.evaluate(() => {
      const containerEl = [...document.querySelectorAll("div")].find(
        (d) => getComputedStyle(d).containerName === "builder"
      );
      const scroller = containerEl?.firstElementChild as HTMLElement;
      const planPane = document.getElementById("ai-builder-plan-pane");
      const actionBar = planPane?.querySelector<HTMLElement>("div.sticky.bottom-0");
      if (!scroller || !planPane || !actionBar) throw new Error("layout regions missing");

      const scrollPaddingBottom = parseFloat(getComputedStyle(scroller).scrollPaddingBottom);
      const actionBarHeight = actionBar.getBoundingClientRect().height;

      const focusables = [...planPane.querySelectorAll<HTMLElement>("button, a[href]")].filter(
        (el) => !actionBar.contains(el) && el.offsetParent !== null
      );
      const target = focusables[focusables.length - 1];
      if (!target) throw new Error("no focusable plan content control");
      scroller.scrollTop = 0;
      target.focus();

      const targetRect = target.getBoundingClientRect();
      const barRect = actionBar.getBoundingClientRect();
      return {
        scrollPaddingBottom,
        actionBarHeight,
        focusedAboveBar: targetRect.bottom <= barRect.top + 0.5,
        focused: document.activeElement === target
      };
    });

    expect(clearance.scrollPaddingBottom).toBeGreaterThanOrEqual(clearance.actionBarHeight + 16);
    expect(clearance.focused).toBe(true);
    expect(clearance.focusedAboveBar).toBe(true);
  });

  test("reduced motion disables collapsible height animation", async ({ page, request }) => {
    await page.emulateMedia({ reducedMotion: "reduce" });
    await page.setViewportSize({ width: 1440, height: 900 });
    await openPlanReview(page, request);

    const animationName = await page.evaluate((triggerText) => {
      const trigger = [...document.querySelectorAll<HTMLButtonElement>("button")].find((button) =>
        button.textContent?.includes(triggerText)
      );
      const content = trigger
        ?.closest("section")
        ?.querySelector<HTMLElement>('[data-slot="collapsible-content"].collapsible-animate');
      if (!trigger || !content) throw new Error("rationale disclosure missing");
      trigger.click();
      return getComputedStyle(content).animationName;
    }, RATIONALE_TRIGGER);

    expect(animationName).toBe("none");
  });
});

test.describe("AI Builder touch targets", () => {
  test.use({ hasTouch: true, isMobile: true, viewport: { width: 390, height: 844 } });

  test("disclosure triggers meet the 44px touch-target minimum", async ({ page, request }) => {
    await openPlanReview(page, request);

    expect(await page.evaluate(() => window.matchMedia("(pointer: coarse)").matches)).toBe(true);

    await page.getByRole("button", { name: "Plan", exact: true }).click();
    const rationale = page.getByRole("button", { name: RATIONALE_TRIGGER });
    await rationale.scrollIntoViewIfNeeded();
    expect(
      await rationale.evaluate((el) => el.getBoundingClientRect().height)
    ).toBeGreaterThanOrEqual(44);

    await page.getByRole("button", { name: "Uppgift", exact: true }).click();
    const assumptions = page.getByRole("button", { name: /^Antaganden \(1\)$/ });
    await assumptions.scrollIntoViewIfNeeded();
    expect(
      await assumptions.evaluate((el) => el.getBoundingClientRect().height)
    ).toBeGreaterThanOrEqual(44);
  });
});
