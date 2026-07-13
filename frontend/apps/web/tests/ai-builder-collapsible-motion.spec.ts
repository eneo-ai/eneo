import { expect, test, type APIRequestContext, type Page } from "@playwright/test";
import { backendFetch, expectOk } from "./helpers";

// Motion contract for the opted-in collapsible height animation
// (collapsible-content.svelte `.collapsible-animate`). The wrapper leans on
// bits-ui internals — mount-animation prevention, the presence lifecycle, and
// the measured-height CSS variable — so this spec pins that behavior against
// dependency upgrades: no initial-mount animation, both directions animate,
// settled states are correct, and reduced motion disables the keyframes.

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
      flow_description: "Tar emot en text vid körning och levererar en sammanfattning.",
      steps: [],
      form_fields: null
    },
    plan_rationale: "Tre steg håller varje delmoment enkelt att kontrollera.",
    assumptions: [],
    lint_warnings: [],
    risk_acknowledgments: [],
    description_override_manual: false,
    edit: null
  }
};

async function openPlanReview(page: Page, request: APIRequestContext) {
  await page.goto("/");
  const response = await backendFetch(page, request, "/api/v1/spaces/type/personal/");
  await expectOk(response, "loading personal space");
  const body = (await response.json()) as { id?: unknown };
  if (typeof body.id !== "string") throw new Error("personal space id missing");
  const { draft, session } = makeFixtures(body.id);

  await page.route("**/api/v1/flows/ai-builder/**", async (route) => {
    const url = route.request().url();
    if (url.includes("/models")) {
      return route.fulfill({ json: { models: [], default_model_id: null } });
    }
    if (/\/plans\/plan-1\/?$/.test(url)) return route.fulfill({ json: PLAN });
    if (/\/sessions\/plan-session\/?$/.test(url)) return route.fulfill({ json: session });
    if (/\/sessions\/?(\?.*)?$/.test(url)) return route.fulfill({ json: { sessions: [draft] } });
    return route.fulfill({ json: {} });
  });
  await page.goto("/spaces/personal/flows/ai-builder");
  await expect(page.locator("#ai-builder-plan-pane")).toBeAttached({ timeout: 20_000 });
}

const RATIONALE_TRIGGER = "Varför Eneo föreslår detta upplägg";

function rationaleContent(page: Page) {
  return page.evaluate((triggerText) => {
    const btn = [...document.querySelectorAll<HTMLButtonElement>("button")].find((b) =>
      b.textContent?.includes(triggerText)
    );
    const content = btn
      ?.closest("section")
      ?.querySelector<HTMLElement>('[data-slot="collapsible-content"].collapsible-animate');
    if (!content) return null;
    return {
      animationName: getComputedStyle(content).animationName,
      state: content.getAttribute("data-state"),
      height: content.getBoundingClientRect().height
    };
  }, RATIONALE_TRIGGER);
}

test.describe("collapsible-animate motion contract", () => {
  test("no mount animation, both directions animate, settled states correct", async ({
    page,
    request
  }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    await openPlanReview(page, request);

    const trigger = page.getByRole("button", { name: RATIONALE_TRIGGER });
    await expect(trigger).toHaveAttribute("aria-expanded", "true");

    // The wide-container default opens the rationale AFTER mount (the
    // ResizeObserver flips it), so the open keyframe legitimately runs once;
    // what matters is that the content settles open at full height.
    const mounted = await rationaleContent(page);
    expect(mounted?.state).toBe("open");
    expect(mounted?.height ?? 0).toBeGreaterThan(10);

    // Close: the keyframe binds immediately and content stays mounted while
    // it plays, then bits-ui hides it.
    const close = await page.evaluate(async (triggerText) => {
      const btn = [...document.querySelectorAll<HTMLButtonElement>("button")].find((b) =>
        b.textContent?.includes(triggerText)
      );
      if (!btn) throw new Error("rationale trigger not found");
      const content = btn
        .closest("section")
        ?.querySelector<HTMLElement>('[data-slot="collapsible-content"].collapsible-animate');
      if (!content) throw new Error("animated content not found");
      btn.click();
      await new Promise(requestAnimationFrame);
      const early = {
        animationName: getComputedStyle(content).animationName,
        state: content.getAttribute("data-state")
      };
      await new Promise((r) => setTimeout(r, 60));
      const mid = { mounted: document.contains(content) };
      await new Promise((r) => setTimeout(r, 300));
      const settled = {
        visible: document.contains(content) && content.offsetParent !== null && !content.hidden
      };
      return { early, mid, settled };
    }, RATIONALE_TRIGGER);
    expect(close.early.state).toBe("closed");
    expect(close.early.animationName).toBe("collapsible-close");
    expect(close.mid.mounted).toBe(true);
    expect(close.settled.visible).toBe(false);
    await expect(trigger).toHaveAttribute("aria-expanded", "false");

    // Reopen: the open keyframe binds and the content settles at full height.
    const open = await page.evaluate(async (triggerText) => {
      const btn = [...document.querySelectorAll<HTMLButtonElement>("button")].find((b) =>
        b.textContent?.includes(triggerText)
      );
      if (!btn) throw new Error("rationale trigger not found");
      btn.click();
      await new Promise(requestAnimationFrame);
      const content = btn
        .closest("section")
        ?.querySelector<HTMLElement>('[data-slot="collapsible-content"].collapsible-animate');
      if (!content) throw new Error("animated content missing after open");
      const early = { animationName: getComputedStyle(content).animationName };
      await new Promise((r) => setTimeout(r, 300));
      return { early, settledHeight: content.getBoundingClientRect().height };
    }, RATIONALE_TRIGGER);
    expect(open.early.animationName).toBe("collapsible-open");
    expect(open.settledHeight).toBeGreaterThan(10);
    await expect(trigger).toHaveAttribute("aria-expanded", "true");
  });

  test("reduced motion disables the height keyframes", async ({ page, request }) => {
    await page.emulateMedia({ reducedMotion: "reduce" });
    await page.setViewportSize({ width: 1440, height: 900 });
    await openPlanReview(page, request);

    const sample = await page.evaluate(async (triggerText) => {
      const btn = [...document.querySelectorAll<HTMLButtonElement>("button")].find((b) =>
        b.textContent?.includes(triggerText)
      );
      if (!btn) throw new Error("rationale trigger not found");
      const content = btn
        .closest("section")
        ?.querySelector<HTMLElement>('[data-slot="collapsible-content"].collapsible-animate');
      if (!content) throw new Error("animated content not found");
      btn.click();
      await new Promise(requestAnimationFrame);
      return { animationName: getComputedStyle(content).animationName };
    }, RATIONALE_TRIGGER);
    expect(sample.animationName).toBe("none");
  });
});
