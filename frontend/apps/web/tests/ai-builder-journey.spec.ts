import { expect, test, type APIRequestContext, type Page, type Route } from "@playwright/test";
import { backendFetch, expectOk } from "./helpers";

// The builder journey against a scripted backend: every message turn answers
// with a fixed SSE script so the run is deterministic and cheap. Copy below
// must track messages/sv.json (rail, question, confirm and plan strings).
const RAIL_LABEL = "AI-byggarens förlopp";
const RAIL_UNDERSTANDING = "Eneo förstår uppgiften";
const RAIL_REVIEWING = "Du granskar innan det skapas";
const CONFIRM_TITLE = "Så här har Eneo förstått uppgiften";
const CONFIRM_ACTION = "Stämmer — utforma planen";
const CONFIRM_STALE = "Uppdaterad — bekräfta igen.";
const QUESTION_CONFIRM = "Bekräfta svaret";
const HOW_FLOW_WORKS = "Så fungerar flödet";

const V1 = "a".repeat(64);
const V2 = "b".repeat(64);
const PLAN_ID = "11111111-1111-4111-8111-111111111111";

const QUESTION = {
  question_id: "output_format",
  question: "Vad ska flödet producera som slutresultat?",
  options: [
    { id: "pdf", label: "PDF-dokument", description: "En färdig PDF som slutresultat." },
    { id: "text", label: "Strukturerat textresultat", description: "En sida text." }
  ],
  selection_mode: "single",
  allow_custom: false
};

function summary(version: string) {
  return {
    requirements_version: version,
    summary: "Vid körning tar flödet emot ljud och levererar PDF-dokument.",
    key_decisions: [{ topic: "Slutresultat", decision: "PDF-dokument" }],
    input_description: "Ljud",
    output_description: "PDF-dokument",
    assumptions: ["Rapporten skrivs på svenska."]
  };
}

const PLAN = {
  plan_id: PLAN_ID,
  proposal: {
    spec: {
      flow_name: "Ljud till strukturerad PDF-rapport",
      flow_description: "Transkriberar en ljudfil och sammanställer en PDF-rapport.",
      steps: [
        {
          plan_step_ref: "step_a",
          existing_step_ref: null,
          name: "Transkribera ljud",
          assistant_spec: { instructions: "Transkribera ljudet.", model_ref: null },
          input_source: "flow_input",
          input_type: "audio",
          output_mode: "transcribe_only",
          output_type: "text"
        },
        {
          plan_step_ref: "step_b",
          existing_step_ref: null,
          name: "Skriv rapport",
          assistant_spec: { instructions: "Skriv en rapport.", model_ref: "gpt-5" },
          input_source: "previous_step",
          input_type: "text",
          output_mode: "compose_text",
          output_type: "text"
        }
      ],
      form_fields: null
    },
    assumptions: ["Rapporten skrivs på svenska."],
    lint_warnings: [],
    plan_rationale: "Två steg räcker.",
    description_override_manual: false,
    edit: null,
    execution_shape: {
      completion_model_step_count: 1,
      transcription_model_step_count: 1,
      deterministic_step_count: 0,
      schema_constrained_step_count: 0,
      mapped_step_upper_bounds: []
    }
  }
};

type Frame = { event: string; data: unknown };
function sse(frames: Frame[]): string {
  return (
    frames
      .map(
        (frame) =>
          `event: ${frame.event}\ndata: ${frame.event === "done" ? "" : JSON.stringify(frame.data)}\n`
      )
      .join("\n") + "\n"
  );
}

async function personalSpaceId(page: Page, request: APIRequestContext): Promise<string> {
  const response = await backendFetch(page, request, "/api/v1/spaces/type/personal/");
  await expectOk(response, "loading personal space");
  const body = (await response.json()) as { id?: unknown };
  if (typeof body.id !== "string") throw new Error("personal space id missing");
  return body.id;
}

interface Script {
  /** Answer for the n-th message turn (0-based). */
  turns: Frame[][];
}

async function stubBuilder(page: Page, spaceId: string, script: Script) {
  const session = {
    session_id: "journey-session",
    space_id: spaceId,
    status: "chatting",
    target_kind: "create",
    flow_id: null,
    latest_plan_id: null,
    draft_title: null,
    created_at: "2026-08-16T09:00:00Z",
    updated_at: "2026-08-16T09:00:00Z",
    conversation: [],
    attachments: [],
    attachment_warnings: [],
    latest_turn: null
  };
  let turn = 0;
  await page.route("**/api/v1/flows/ai-builder/**", async (route: Route) => {
    const url = route.request().url();
    const method = route.request().method();
    if (url.includes("/models")) {
      return route.fulfill({ json: { models: [], default_model_id: null } });
    }
    if (/\/messages\/?$/.test(url) && method === "POST") {
      const frames = script.turns[Math.min(turn, script.turns.length - 1)] ?? [];
      turn += 1;
      return route.fulfill({
        status: 200,
        headers: { "content-type": "text/event-stream" },
        body: sse([...frames, { event: "done", data: "" }])
      });
    }
    if (/\/plans\/[^/]+\/?$/.test(url)) {
      return route.fulfill({
        json: { ...PLAN, session_id: session.session_id, status: "proposed" }
      });
    }
    if (/\/sessions\/journey-session\/?$/.test(url)) {
      return route.fulfill({ json: session });
    }
    if (/\/sessions\/?(\?.*)?$/.test(url)) {
      if (method === "POST") return route.fulfill({ json: session });
      return route.fulfill({ json: { sessions: [] } });
    }
    return route.fulfill({ json: {} });
  });
}

async function openBuilder(page: Page, request: APIRequestContext, script: Script) {
  await page.goto("/");
  const spaceId = await personalSpaceId(page, request);
  await stubBuilder(page, spaceId, script);
  await page.goto("/spaces/personal/flows/ai-builder");
  await expect(page.getByRole("navigation", { name: RAIL_LABEL })).toBeVisible({ timeout: 20_000 });
}

async function sendTask(page: Page) {
  const composer = page.getByRole("textbox").first();
  await composer.fill("Ljudfilen från ett nämndmöte ska bli en PDF-rapport");
  await page.getByRole("button", { name: "Skicka" }).click();
}

test.describe("AI builder journey", () => {
  test("happy path: task → question → confirm → plan", async ({ page, request }) => {
    await openBuilder(page, request, {
      turns: [
        [
          { event: "text", data: { text: "Jag behöver veta slutresultatet." } },
          { event: "question", data: QUESTION }
        ],
        [{ event: "requirements_summary", data: summary(V1) }],
        [
          { event: "status", data: { status: "architecture_committed" } },
          { event: "plan", data: PLAN },
          // The server always closes a committed turn with a usage frame.
          { event: "usage", data: { total_tokens_total: 1200, last_model: "gpt-5" } }
        ]
      ]
    });
    await sendTask(page);

    // Question: choose then confirm.
    await expect(page.getByRole("heading", { name: QUESTION.question })).toBeVisible();
    await page.getByRole("radio", { name: /PDF-dokument/ }).click();
    await page.getByRole("button", { name: QUESTION_CONFIRM }).click();

    // Confirm card is the contract.
    await expect(page.getByText(CONFIRM_TITLE).first()).toBeVisible();
    await page.getByRole("button", { name: CONFIRM_ACTION }).click();

    // Plan lands on the review phase.
    await expect(page.getByRole("heading", { name: HOW_FLOW_WORKS })).toBeVisible({
      timeout: 15_000
    });
    const rail = page.getByRole("navigation", { name: RAIL_LABEL });
    await expect(rail.getByRole("button", { name: RAIL_REVIEWING })).toHaveAttribute(
      "aria-current",
      "step"
    );
    // The confirmed requirements can be revisited from the rail.
    await rail.getByRole("button", { name: RAIL_UNDERSTANDING }).click();
    await expect(page.getByText(CONFIRM_TITLE).first()).toBeVisible();
  });

  test("a changed answer re-arms the confirmation", async ({ page, request }) => {
    await openBuilder(page, request, {
      turns: [
        [{ event: "requirements_summary", data: summary(V1) }],
        // The confirmation turn: the server discloses a NEW version instead of building.
        [
          { event: "text", data: { text: "Jag har uppdaterat sammanfattningen." } },
          { event: "requirements_summary", data: summary(V2) }
        ]
      ]
    });
    await sendTask(page);
    await expect(page.getByText(CONFIRM_TITLE).first()).toBeVisible();
    await page.getByRole("button", { name: CONFIRM_ACTION }).click();

    await expect(page.getByText(CONFIRM_STALE)).toBeVisible({ timeout: 15_000 });
    await expect(page.getByRole("button", { name: CONFIRM_ACTION })).toBeEnabled();
  });
});
