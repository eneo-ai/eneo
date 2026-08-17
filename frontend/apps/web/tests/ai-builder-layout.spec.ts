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
      },
      // A plan only exists against a confirmed disclosure.
      {
        message_id: "m-3",
        role: "user",
        content: "",
        timestamp: "2026-07-11T09:06:00Z",
        requirements_confirmation: { requirements_confirmed: true, requirements_version: "v1" }
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
      if (route.request().method() === "POST") {
        return route.fulfill({
          json: {
            ...draft,
            session_id: "fresh-session",
            status: "chatting",
            latest_plan_id: null,
            conversation: [],
            latest_turn: null
          }
        });
      }
      return route.fulfill({ json: { sessions: [draft] } });
    }
    if (/\/sessions\/fresh-session\/?$/.test(url)) {
      return route.fulfill({
        json: {
          ...draft,
          session_id: "fresh-session",
          status: "chatting",
          latest_plan_id: null,
          conversation: [],
          latest_turn: null
        }
      });
    }
    return route.fulfill({ json: {} });
  });
}

// The phase rail and its labels must track messages/sv.json (`ai_builder_rail_*`,
// `ai_builder_progress_aria`); the plan surface heading is `ai_builder_how_flow_works`.
const RAIL_LABEL = "AI-byggarens förlopp";
const RAIL_UNDERSTANDING = "Eneo förstår uppgiften";
const RAIL_PLANNING = "Eneo utformar planen";
const RAIL_REVIEWING = "Du granskar innan det skapas";
const HOW_FLOW_WORKS = "Så fungerar flödet";
const CONVERSATION_BUTTON = "Samtal";
const CONVERSATION_TITLE = "Samtalet";
const CONFIRM_TITLE = "Så här har Eneo förstått uppgiften";
const TASK_TITLE = "Vad ska flödet göra?";
const PLAN_CARD = PLAN.proposal.spec.flow_name;

async function openBuilder(page: Page, request: APIRequestContext, query = "") {
  await page.goto("/");
  const spaceId = await personalSpaceId(page, request);
  await stubAiBuilderApi(page, spaceId);
  await page.goto(`/spaces/personal/flows/ai-builder${query}`);
  await expect(page.getByRole("navigation", { name: RAIL_LABEL })).toBeVisible({ timeout: 20_000 });
}

test.describe("AI builder phase shell", () => {
  test("a resumed draft with a plan opens on the review phase", async ({ page, request }) => {
    await openBuilder(page, request, "?session=plan-session");
    const rail = page.getByRole("navigation", { name: RAIL_LABEL });
    await expect(rail.getByRole("button", { name: RAIL_REVIEWING })).toHaveAttribute(
      "aria-current",
      "step"
    );
    await expect(page.getByRole("heading", { name: HOW_FLOW_WORKS })).toBeVisible();
    // The build phase has nothing to revisit once it is done.
    await expect(rail.getByRole("button", { name: RAIL_PLANNING })).toBeDisabled();
  });

  test("a completed phase can be revisited without leaving the plan", async ({ page, request }) => {
    await openBuilder(page, request, "?session=plan-session");
    const rail = page.getByRole("navigation", { name: RAIL_LABEL });
    await rail.getByRole("button", { name: RAIL_UNDERSTANDING }).click();
    await expect(page.getByText(CONFIRM_TITLE).first()).toBeVisible();
    await rail.getByRole("button", { name: RAIL_REVIEWING }).click();
    await expect(page.getByRole("heading", { name: HOW_FLOW_WORKS })).toBeVisible();
  });

  test("the conversation is one gesture away", async ({ page, request }) => {
    await openBuilder(page, request, "?session=plan-session");
    await page.getByRole("button", { name: new RegExp(`^${CONVERSATION_BUTTON}`) }).click();
    const sheet = page.getByRole("dialog");
    await expect(sheet.getByText(CONVERSATION_TITLE)).toBeVisible();
    await expect(sheet.getByText("Sammanfatta rapporter till en PDF")).toBeVisible();
    await page.keyboard.press("Escape");
    await expect(sheet).toBeHidden();
  });

  test("a new task starts on the task screen with the composer", async ({ page, request }) => {
    await openBuilder(page, request);
    await expect(page.getByRole("heading", { name: TASK_TITLE })).toBeVisible();
    const composer = page.getByRole("textbox").first();
    await expect(composer).toBeVisible();
    await expect(page.getByRole("button", { name: "Skicka" })).toBeDisabled();
    await composer.fill("Sammanfatta rapporter");
    await expect(page.getByRole("button", { name: "Skicka" })).toBeEnabled();
  });

  // The header column is sized to the review card, so the rail starts on the
  // same line as the plan — the surface the user spends the most time on.
  test("the rail starts on the same line as the plan", async ({ page, request }) => {
    await openBuilder(page, request, "?session=plan-session");
    const rail = page.getByRole("navigation", { name: RAIL_LABEL });
    const planCard = page.getByRole("article", { name: PLAN_CARD });
    await expect(planCard).toBeVisible();

    for (const width of [1280, 1440, 2560]) {
      await page.setViewportSize({ width, height: 900 });
      const railBox = await rail.boundingBox();
      const planBox = await planCard.boundingBox();
      expect(railBox, `rail at ${width}px`).not.toBeNull();
      expect(planBox, `plan card at ${width}px`).not.toBeNull();
      expect(Math.abs(railBox!.x - planBox!.x), `alignment at ${width}px`).toBeLessThanOrEqual(2);
    }
  });

  test("the rail collapses to one line on a phone", async ({ page, request }) => {
    await page.setViewportSize({ width: 375, height: 812 });
    await openBuilder(page, request, "?session=plan-session");
    const compact = page.locator(".rail-compact");
    await expect(compact).toBeVisible();
    await expect(compact).toContainText(RAIL_REVIEWING);
    await expect(page.locator(".rail-list")).toBeHidden();
  });

  test("motion is disabled under prefers-reduced-motion", async ({ page, request }) => {
    await page.emulateMedia({ reducedMotion: "reduce" });
    await openBuilder(page, request);
    await expect(page.getByRole("heading", { name: TASK_TITLE })).toBeVisible();
    const target = page.locator(".task-screen");
    await expect(target).toHaveCount(1);
    const animation = await target.evaluate((el) => getComputedStyle(el).animationName);
    expect(animation).toBe("none");
  });
});
