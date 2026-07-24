import { expect, test, type APIRequestContext, type Page } from "@playwright/test";
import { backendFetch, expectOk } from "./helpers";

// Responsive layout contract for the AI-builder plan-review shell
// (docs/flows/plan-review-handoff.md §1). The AI-builder API is stubbed at the
// network layer with a canned proposed-plan session, so the spec asserts pure
// layout behavior — no provider work, no dependency on planner backends.

// The driver only recovers drafts belonging to the current space, so the
// fixture must carry the REAL personal-space id from the e2e backend.
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
  // The auth cookie is only readable after a first navigation in this context.
  await page.goto("/");
  const spaceId = await personalSpaceId(page, request);
  await stubAiBuilderApi(page, spaceId);
  await page.goto("/spaces/personal/flows/ai-builder");
  // The single stubbed draft auto-resumes into the plan-review state.
  await expect(page.locator("#ai-builder-plan-pane")).toBeAttached({ timeout: 20_000 });
}

function layoutMetrics(page: Page) {
  return page.evaluate(() => {
    const containerEl = [...document.querySelectorAll("div")].find(
      (d) => getComputedStyle(d).containerName === "builder"
    );
    if (!containerEl) throw new Error("builder container not found");
    const inner = containerEl.firstElementChild as HTMLElement;
    const workspace = document.getElementById("ai-builder-task-pane")?.parentElement as HTMLElement;
    const task = document.getElementById("ai-builder-task-pane");
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
      workspaceMaxWidth: workspace ? getComputedStyle(workspace).maxWidth : null,
      workspaceLeft: workspace ? workspace.getBoundingClientRect().left : null,
      containerLeft: containerEl.getBoundingClientRect().left,
      taskWidth: task ? task.getBoundingClientRect().width : null,
      taskRegionOverflowY: taskRegion ? getComputedStyle(taskRegion).overflowY : null,
      planRegionOverflowY: planRegion ? getComputedStyle(planRegion).overflowY : null,
      stickyGroupPosition: stickyGroup ? getComputedStyle(stickyGroup).position : null,
      compactVisible: compact ? getComputedStyle(compact).display !== "none" : null,
      phaseListVisible: phaseList ? getComputedStyle(phaseList).display !== "none" : null
    };
  });
}

// The split threshold is a CONTAINER query; the app shell (sidebar etc.)
// consumes viewport width, so tests derive the viewport that produces an
// exact container width instead of assuming one.
async function viewportForContainerWidth(page: Page, target: number): Promise<number> {
  const probe = 1400;
  await page.setViewportSize({ width: probe, height: 620 });
  const { containerWidth } = await layoutMetrics(page);
  return probe - containerWidth + target;
}

test.describe("AI-builder plan-review layout contract", () => {
  test("split view: page never scrolls, panes own scroll, left pane is clamped", async ({
    page,
    request
  }) => {
    await page.setViewportSize({ width: 1440, height: 620 });
    await openPlanReview(page, request);

    const m = await layoutMetrics(page);
    expect(m.containerWidth).toBeGreaterThanOrEqual(1040);
    expect(m.innerOverflowY).toBe("hidden");
    expect(m.taskRegionOverflowY).toBe("auto");
    expect(m.planRegionOverflowY).toBe("auto");
    expect(m.compactVisible).toBe(false);
    expect(m.phaseListVisible).toBe(true);

    // clamp(340px|380px, 37cqw, 480px) depending on the container tier.
    const lower = m.containerWidth >= 1180 ? 380 : 340;
    const expected = Math.min(480, Math.max(lower, 0.37 * m.containerWidth));
    expect(Math.abs((m.taskWidth ?? 0) - expected)).toBeLessThanOrEqual(1.5);

    await expect(page.getByRole("button", { name: "Uppgift", exact: true })).toBeHidden();
  });

  test("the 1040px container boundary flips between tabs and split", async ({ page, request }) => {
    await openPlanReview(page, request);

    // The shell can produce fractional container widths (clientWidth rounds),
    // so the boundary is pinned with a pincer around 1040 instead of exact
    // integers: split must hold at ~1042 and tabs must hold at ~1038.
    const splitViewport = await viewportForContainerWidth(page, 1042);
    await page.setViewportSize({ width: splitViewport, height: 620 });
    let m = await layoutMetrics(page);
    expect(m.containerWidth).toBeGreaterThanOrEqual(1040);
    expect(m.containerWidth).toBeLessThanOrEqual(1043);
    expect(m.innerOverflowY).toBe("hidden");
    await expect(page.getByRole("button", { name: "Uppgift", exact: true })).toBeHidden();

    await page.setViewportSize({ width: splitViewport - 4, height: 620 });
    m = await layoutMetrics(page);
    expect(m.containerWidth).toBeLessThan(1040);
    expect(m.containerWidth).toBeGreaterThanOrEqual(1036);
    expect(m.innerOverflowY).toBe("auto");
    expect(m.compactVisible).toBe(true);
    expect(m.phaseListVisible).toBe(false);
    await expect(page.getByRole("button", { name: "Uppgift", exact: true })).toBeVisible();
  });

  test("the rationale default follows the builder container width until the user touches it", async ({
    page,
    request
  }) => {
    await openPlanReview(page, request);
    const trigger = page.getByRole("button", { name: "Varför Eneo föreslår detta upplägg" });

    // ≥768px container (§1.5): open by default.
    const wideViewport = await viewportForContainerWidth(page, 800);
    await page.setViewportSize({ width: wideViewport, height: 620 });
    await expect(trigger).toHaveAttribute("aria-expanded", "true");

    // <768px container: collapsed by default — even though the VIEWPORT is
    // far wider than 768 (the threshold is container-owned, §1).
    const narrowViewport = await viewportForContainerWidth(page, 740);
    expect(narrowViewport).toBeGreaterThan(768);
    await page.setViewportSize({ width: narrowViewport, height: 620 });
    await expect(trigger).toHaveAttribute("aria-expanded", "false");

    // Once the user opens it, resizing no longer overrides their choice.
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

      // Focus the last interactive control in the plan CONTENT (not the
      // action bar itself); the browser scrolls it into view respecting the
      // scroll owner's scroll-padding.
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

    // §1.3: clearance = fixed-region height + 16px. The stacked mobile action
    // bar must fit inside the reserved scroll padding.
    expect(clearance.scrollPaddingBottom).toBeGreaterThanOrEqual(clearance.actionBarHeight + 16);
    expect(clearance.focused).toBe(true);
    expect(clearance.focusedAboveBar).toBe(true);
  });

  test("very wide containers cap and center the workspace at 1760px", async ({ page, request }) => {
    await openPlanReview(page, request);
    const capViewport = await viewportForContainerWidth(page, 1800);
    await page.setViewportSize({ width: capViewport, height: 700 });

    const m = await layoutMetrics(page);
    // If this environment's app shell cannot yield a ≥1760px container, say so
    // loudly instead of silently passing on the uncapped branch.
    test.skip(
      m.containerWidth < 1760,
      `app shell caps the container at ${m.containerWidth}px in this environment — 1760 cap not reachable`
    );
    expect(m.workspaceMaxWidth).toBe("1760px");
    // Centered: the workspace starts to the right of the container edge.
    expect((m.workspaceLeft ?? 0) - m.containerLeft).toBeGreaterThan(10);
  });
});
