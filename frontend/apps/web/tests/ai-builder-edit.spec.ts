import {
  expect,
  test,
  type APIRequestContext,
  type Locator,
  type Page,
  type Route
} from "@playwright/test";
import { backendFetch, expectOk, uniqueName } from "./helpers";

// The edit-side builder journeys. The flow itself is real — created through the
// backend API — while every AI Builder turn answers from a fixed SSE script, so
// the run is deterministic and costs no model call.
//
// Copy below is quoted from messages/sv.json; the message key is named beside
// each string so a copy change fails here instead of drifting silently.
const AI_BUILDER_TAB = "AI-byggaren"; // ai_builder_tab
const BUILDER_TAB = "Byggare"; // flow_builder
const STAGE_PROCESSING_STEPS = "Bearbetningssteg"; // flow_stage_processing_steps
const CHANGE_STEP_WITH_AI = "Ändra det här steget med AI"; // flow_step_change_with_ai
const TASK_TITLE_EDIT = "Vad ska ändras i flödet?"; // ai_builder_task_title_edit
const TASK_TITLE = "Vad ska flödet göra?"; // ai_builder_task_title
const SAVED_STEP_PLACEHOLDER = "Beskriv vad du vill ändra i det valda steget..."; // ai_builder_saved_step_prompt_placeholder
const SEND = "Skicka"; // ai_builder_send
const RAIL_LABEL = "AI-byggarens förlopp"; // ai_builder_progress_aria
const HOW_FLOW_WORKS = "Så fungerar flödet"; // ai_builder_how_flow_works
const APPROVE = "Godkänn"; // ai_builder_approve
const APPLY = "Tillämpa"; // ai_builder_apply
const APPLY_CONFIRM = "Uppdatera flödet"; // ai_builder_approve_dialog_confirm_edit
const CONVERSATION_BUTTON = "Samtal"; // ai_builder_conversation_button
const EDIT_ANSWER = "Ändra det här svaret"; // ai_builder_conversation_edit_answer
const ANSWER_IN_VIEW = "— besvaras i byggaren"; // ai_builder_question_answer_in_view
const EDITING_NOTE = "Du ändrar ett tidigare svar."; // ai_builder_question_editing_note
const QUESTION_CONFIRM = "Bekräfta svaret"; // ai_builder_question_confirm
const REFERENCE_MATERIAL = "Referensmaterial"; // ai_builder_reference_material
const CONFIRM_ATTACHMENTS = "Bifogade filer"; // ai_builder_confirm_attachments
const CONFIRM_TITLE = "Så här har Eneo förstått uppgiften"; // ai_builder_requirements_title

// ai_builder_edit_context_step: "Redigerar steg {step}: {name}"
function editContextStepLabel(step: number, name: string) {
  return `Redigerar steg ${step}: ${name}`;
}

const PLAN_ID = "22222222-2222-4222-8222-222222222222";
const REQUIREMENTS_VERSION = "c".repeat(64);

// ---- Scripted transport ----------------------------------------------------

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

type SessionBody = Record<string, unknown>;

interface ScriptedTurn {
  frames: Frame[];
  /** What a GET of the session returns once this turn has been streamed. */
  session?: SessionBody;
}

interface BuilderStubOptions {
  spaceId: string;
  flowId: string | null;
  targetKind: "create" | "edit";
  turns: ScriptedTurn[];
  plan?: Record<string, unknown> | null;
  applyResult?: Record<string, unknown> | null;
}

interface BuilderStub {
  /** Bodies of every POST to .../messages, in order. */
  messageRequests: Record<string, unknown>[];
}

const SESSION_ID = "edit-session";

async function stubBuilder(page: Page, options: BuilderStubOptions): Promise<BuilderStub> {
  const messageRequests: Record<string, unknown>[] = [];
  let session: SessionBody = {
    session_id: SESSION_ID,
    space_id: options.spaceId,
    status: "chatting",
    target_kind: options.targetKind,
    flow_id: options.flowId,
    latest_plan_id: null,
    draft_title: null,
    created_at: "2026-08-16T09:00:00Z",
    updated_at: "2026-08-16T09:00:00Z",
    conversation: [],
    attachments: [],
    attachment_warnings: [],
    latest_turn: null
  };
  let planStatus = "proposed";
  let turn = 0;

  await page.route("**/api/v1/flows/ai-builder/**", async (route: Route) => {
    const url = route.request().url();
    const method = route.request().method();

    if (url.includes("/models")) {
      return route.fulfill({ json: { models: [], default_model_id: null } });
    }
    if (/\/messages\/?$/.test(url) && method === "POST") {
      messageRequests.push((route.request().postDataJSON() ?? {}) as Record<string, unknown>);
      const scripted = options.turns[Math.min(turn, options.turns.length - 1)];
      turn += 1;
      if (scripted?.session) session = scripted.session;
      return route.fulfill({
        status: 200,
        headers: { "content-type": "text/event-stream" },
        body: sse([...(scripted?.frames ?? []), { event: "done", data: "" }])
      });
    }
    if (/\/plans\/[^/]+\/approve\/?$/.test(url)) {
      planStatus = "approved";
      return route.fulfill({ json: { plan_id: PLAN_ID, status: "approved" } });
    }
    if (/\/plans\/[^/]+\/apply\/?$/.test(url)) {
      planStatus = "applied";
      session = { ...session, status: "applied", flow_id: options.flowId };
      return route.fulfill({ json: options.applyResult ?? {} });
    }
    if (/\/plans\/[^/]+\/?$/.test(url)) {
      return route.fulfill({
        json: { ...(options.plan ?? {}), session_id: SESSION_ID, status: planStatus }
      });
    }
    if (new RegExp(`/sessions/${SESSION_ID}/?$`).test(url)) {
      return route.fulfill({ json: session });
    }
    if (/\/sessions\/?(\?.*)?$/.test(url)) {
      if (method === "POST") return route.fulfill({ json: session });
      return route.fulfill({ json: { sessions: [] } });
    }
    return route.fulfill({ json: {} });
  });

  return { messageRequests };
}

// ---- Real flow fixtures ----------------------------------------------------

interface CreatedFlow {
  id: string;
  name: string;
  stepId: string;
  stepName: string;
}

const createdFlowIds: string[] = [];

async function apiJson(
  page: Page,
  request: APIRequestContext,
  path: string,
  options: Parameters<typeof backendFetch>[3],
  context: string
): Promise<Record<string, unknown>> {
  const response = await backendFetch(page, request, path, options);
  await expectOk(response, context);
  return (await response.json()) as Record<string, unknown>;
}

function requiredString(record: Record<string, unknown>, key: string, context: string): string {
  const value = record[key];
  if (typeof value !== "string") throw new Error(`${context}.${key} should be a string`);
  return value;
}

/** An unpublished flow with one saved step — the shape the editor's per-step
 *  "Ändra det här steget med AI" action needs. */
async function createFlowWithStep(
  page: Page,
  request: APIRequestContext,
  stepName: string
): Promise<CreatedFlow> {
  const personalSpace = await apiJson(
    page,
    request,
    "/api/v1/spaces/type/personal/",
    {},
    "loading personal space"
  );
  const spaceId = requiredString(personalSpace, "id", "personal space");
  const name = uniqueName("E2E AI Builder Flow");

  const flow = await apiJson(
    page,
    request,
    "/api/v1/flows/",
    {
      method: "POST",
      data: { space_id: spaceId, name, description: "E2E edit journey", steps: [] }
    },
    "creating flow"
  );
  const flowId = requiredString(flow, "id", "flow");
  createdFlowIds.push(flowId);

  const assistant = await apiJson(
    page,
    request,
    `/api/v1/flows/${flowId}/assistants/`,
    { method: "POST", data: { name: uniqueName("E2E AI Builder assistant") } },
    "creating flow-managed assistant"
  );

  const updated = await apiJson(
    page,
    request,
    `/api/v1/flows/${flowId}/`,
    {
      method: "PATCH",
      data: {
        steps: [
          {
            step_order: 1,
            user_description: stepName,
            input_source: "flow_input",
            input_type: "text",
            output_mode: "pass_through",
            output_type: "text",
            assistant_id: requiredString(assistant, "id", "assistant")
          }
        ]
      }
    },
    "adding the flow step"
  );

  const steps = updated.steps;
  if (!Array.isArray(steps) || steps.length !== 1) {
    throw new Error("the flow should have exactly one step");
  }
  return {
    id: flowId,
    name,
    stepId: requiredString(steps[0] as Record<string, unknown>, "id", "flow step"),
    stepName
  };
}

async function personalSpaceId(page: Page, request: APIRequestContext): Promise<string> {
  const personalSpace = await apiJson(
    page,
    request,
    "/api/v1/spaces/type/personal/",
    {},
    "loading personal space"
  );
  return requiredString(personalSpace, "id", "personal space");
}

// ---- Plan fixture ----------------------------------------------------------

/** A whole-flow edit whose diff modifies the one existing step. */
function editPlan(stepRef: string, stepName: string) {
  return {
    plan_id: PLAN_ID,
    proposal: {
      spec: {
        flow_name: "Sammanfattning med källhänvisningar",
        flow_description: "Sammanfattar underlaget och listar källorna.",
        steps: [
          {
            plan_step_ref: "step_a",
            existing_step_ref: stepRef,
            name: stepName,
            assistant_spec: {
              instructions: "Sammanfatta underlaget och lista källorna sist.",
              model_ref: null
            },
            input_source: "flow_input",
            input_type: "text",
            output_mode: "compose_text",
            output_type: "text"
          }
        ],
        form_fields: null
      },
      assumptions: ["Underlaget är på svenska."],
      lint_warnings: [],
      plan_rationale: "Ett steg räcker för att både sammanfatta och lista källorna.",
      description_override_manual: false,
      edit: {
        base_flow_revision: 1,
        removed_existing_step_refs: [],
        scoped_target_existing_step_ref: null,
        scoped_target_plan_step_ref: null,
        diff: {
          step_changes: [
            {
              kind: "modified",
              step_name: stepName,
              step_ref: stepRef,
              details: "Steget listar nu källorna sist."
            }
          ],
          form_changes: [],
          metadata_changes: [],
          net_steps_added: 0,
          net_steps_removed: 0
        },
        warnings: [],
        advisories: [],
        risk_flags: [],
        confidence: "ready"
      },
      execution_shape: {
        completion_model_step_count: 1,
        transcription_model_step_count: 0,
        deterministic_step_count: 0,
        schema_constrained_step_count: 0,
        mapped_step_upper_bounds: []
      }
    }
  };
}

function requirementsSummary() {
  return {
    requirements_version: REQUIREMENTS_VERSION,
    summary: "Vid körning tar flödet emot en text och levererar en sammanfattning.",
    key_decisions: [{ topic: "Slutresultat", decision: "Sammanfattning" }],
    input_description: "Text vid körning",
    output_description: "Sammanfattning",
    assumptions: ["Underlaget är på svenska."],
    manual_setup_notes: []
  };
}

// ---- Page helpers ----------------------------------------------------------

async function openFlowPage(page: Page, flow: CreatedFlow) {
  await page.goto(`/spaces/personal/flows/${flow.id}`);
  await expect(page.getByRole("heading", { name: flow.name })).toBeVisible({ timeout: 20_000 });
}

// "Byggare" is a substring of "AI-byggaren", so both tabs are matched exactly.
function flowTab(page: Page, name: string): Locator {
  return page.getByRole("tab", { name, exact: true });
}

async function openAIBuilderTab(page: Page) {
  await flowTab(page, AI_BUILDER_TAB).click();
  await expect(page.getByRole("navigation", { name: RAIL_LABEL })).toBeVisible({ timeout: 20_000 });
}

function composer(page: Page): Locator {
  return page.getByRole("textbox").first();
}

async function sendFromComposer(page: Page, text: string) {
  await composer(page).fill(text);
  const send = page.getByRole("button", { name: SEND });
  await expect(send).toBeEnabled();
  await send.click();
}

test.describe("AI builder edit journeys", () => {
  test.afterEach(async ({ page, request }) => {
    while (createdFlowIds.length > 0) {
      const flowId = createdFlowIds.pop()!;
      await backendFetch(page, request, `/api/v1/flows/${flowId}/`, { method: "DELETE" });
    }
  });

  test("a whole-flow change is reviewed, approved and applied back into the builder", async ({
    page,
    request
  }) => {
    test.setTimeout(120_000);
    await page.goto("/");
    const spaceId = await personalSpaceId(page, request);
    const flow = await createFlowWithStep(page, request, "Sammanfatta underlaget");
    const plan = editPlan(flow.stepId, "Sammanfatta underlaget");

    await stubBuilder(page, {
      spaceId,
      flowId: flow.id,
      targetKind: "edit",
      plan,
      applyResult: {
        flow_id: flow.id,
        flow_name: flow.name,
        steps_created: 0,
        steps_updated: 1,
        steps_removed: 0
      },
      turns: [
        {
          frames: [
            { event: "status", data: { status: "architecture_committed" } },
            { event: "plan", data: plan },
            // A committed turn always closes with usage; without it the client
            // refreshes from the session and drops the streamed transcript.
            { event: "usage", data: { total_tokens_total: 900, last_model: "gpt-5" } }
          ]
        }
      ]
    });

    await openFlowPage(page, flow);
    await openAIBuilderTab(page);
    await expect(page.getByRole("heading", { name: TASK_TITLE_EDIT })).toBeVisible();

    await sendFromComposer(page, "Lägg till källhänvisningar sist i sammanfattningen");

    await expect(page.getByRole("heading", { name: HOW_FLOW_WORKS })).toBeVisible({
      timeout: 20_000
    });

    await page.getByRole("button", { name: APPROVE }).click();
    const apply = page.getByRole("button", { name: APPLY });
    await expect(apply).toBeEnabled();
    await apply.click();
    // Applying is confirmed in a dialog before anything is written.
    await page.getByRole("alertdialog").getByRole("button", { name: APPLY_CONFIRM }).click();

    // Applying hands the user back to the builder tab with the updated flow.
    await expect(flowTab(page, BUILDER_TAB)).toHaveAttribute("aria-selected", "true", {
      timeout: 20_000
    });
    await expect(page).toHaveURL(/tab=builder/);
  });

  test("a saved step carries its own edit scope into the builder", async ({ page, request }) => {
    test.setTimeout(120_000);
    await page.goto("/");
    const spaceId = await personalSpaceId(page, request);
    const flow = await createFlowWithStep(page, request, "Sammanfatta underlaget");

    const stub = await stubBuilder(page, {
      spaceId,
      flowId: flow.id,
      targetKind: "edit",
      turns: [{ frames: [{ event: "text", data: { text: "Jag tittar bara på det steget." } }] }]
    });

    // A stage that is not current shows its label only from 2xl (1536px) up.
    await page.setViewportSize({ width: 1600, height: 900 });
    await openFlowPage(page, flow);
    await page.getByRole("button", { name: STAGE_PROCESSING_STEPS }).click();
    await page.getByRole("button", { name: CHANGE_STEP_WITH_AI }).click();

    await expect(page.getByRole("navigation", { name: RAIL_LABEL })).toBeVisible({
      timeout: 20_000
    });
    await expect(page.getByRole("heading", { name: TASK_TITLE_EDIT })).toBeVisible();
    await expect(page.getByText(editContextStepLabel(1, flow.stepName))).toBeVisible();
    await expect(composer(page)).toHaveAttribute("placeholder", SAVED_STEP_PLACEHOLDER);

    await sendFromComposer(page, "Skriv resultatet i punktform");

    await expect.poll(() => stub.messageRequests.length, { timeout: 20_000 }).toBeGreaterThan(0);
    expect(stub.messageRequests[0]?.edit_context).toEqual({
      kind: "saved_flow_step",
      flow_step_id: flow.stepId
    });
  });

  test("an earlier answer can be changed from the conversation sheet", async ({
    page,
    request
  }) => {
    test.setTimeout(120_000);
    await page.goto("/");
    const spaceId = await personalSpaceId(page, request);

    const firstQuestion = {
      question_id: "output_format",
      question: "Vad ska flödet producera som slutresultat?",
      options: [
        { id: "pdf", label: "PDF-dokument", description: "En färdig PDF som slutresultat." },
        { id: "text", label: "Strukturerat textresultat", description: "En sida text." }
      ],
      selection_mode: "single",
      allow_custom: false
    };
    const secondQuestion = {
      question_id: "input_material",
      question: "Vilket underlag kommer in vid körning?",
      options: [
        { id: "text", label: "Text", description: "Text klistras in vid körning." },
        { id: "document", label: "Dokument", description: "En fil laddas upp vid körning." }
      ],
      selection_mode: "single",
      allow_custom: false
    };

    const stub = await stubBuilder(page, {
      spaceId,
      flowId: null,
      targetKind: "create",
      turns: [
        {
          frames: [
            { event: "text", data: { text: "Jag behöver veta slutresultatet." } },
            { event: "question", data: firstQuestion }
          ]
        },
        {
          frames: [
            { event: "text", data: { text: "Och vad kommer in?" } },
            { event: "question", data: secondQuestion }
          ]
        },
        { frames: [{ event: "text", data: { text: "Tack, jag har uppdaterat svaret." } }] }
      ]
    });

    await page.goto("/spaces/personal/flows/ai-builder");
    await expect(page.getByRole("navigation", { name: RAIL_LABEL })).toBeVisible({
      timeout: 20_000
    });
    await expect(page.getByRole("heading", { name: TASK_TITLE })).toBeVisible();

    await sendFromComposer(page, "Sammanfatta rapporter till en PDF");
    await expect(page.getByRole("heading", { name: firstQuestion.question })).toBeVisible();
    await page.getByRole("radio", { name: /PDF-dokument/ }).click();
    await page.getByRole("button", { name: QUESTION_CONFIRM }).click();

    await expect(page.getByRole("heading", { name: secondQuestion.question })).toBeVisible({
      timeout: 20_000
    });

    // The sheet separates what is settled from what is still being asked.
    await page.getByRole("button", { name: new RegExp(`^${CONVERSATION_BUTTON}`) }).click();
    const sheet = page.getByRole("dialog");
    const changeAnswer = sheet.getByRole("button", { name: EDIT_ANSWER });
    await expect(changeAnswer).toBeVisible();
    await expect(sheet.locator("p", { hasText: ANSWER_IN_VIEW })).toContainText(
      secondQuestion.question
    );

    await changeAnswer.click();
    await expect(sheet).toBeHidden();
    await expect(page.getByRole("heading", { name: firstQuestion.question })).toBeVisible();
    await expect(page.getByText(EDITING_NOTE)).toBeVisible();

    await page.getByRole("radio", { name: /Strukturerat textresultat/ }).click();
    await page.getByRole("button", { name: QUESTION_CONFIRM }).click();

    await expect.poll(() => stub.messageRequests.length, { timeout: 20_000 }).toBe(3);
    expect(
      (stub.messageRequests[2]?.question_answer as Record<string, unknown> | undefined)?.question_id
    ).toBe(firstQuestion.question_id);
  });

  test("an attached file rides along with the task and shows up on the confirmation", async ({
    page,
    request
  }) => {
    test.setTimeout(120_000);
    await page.goto("/");
    const spaceId = await personalSpaceId(page, request);

    const uploadedFile = {
      id: "33333333-3333-4333-8333-333333333333",
      name: "underlag.txt",
      size: 42,
      mimetype: "text/plain"
    };
    await page.route("**/api/v1/files/", async (route: Route) => {
      if (route.request().method() !== "POST") return route.fallback();
      return route.fulfill({ json: uploadedFile });
    });

    const summary = requirementsSummary();
    const stub = await stubBuilder(page, {
      spaceId,
      flowId: null,
      targetKind: "create",
      turns: [
        {
          frames: [{ event: "requirements_summary", data: summary }],
          // A turn carrying files is always re-read from the server, so the
          // session is what the confirmation renders from.
          session: {
            session_id: SESSION_ID,
            space_id: spaceId,
            status: "chatting",
            target_kind: "create",
            flow_id: null,
            latest_plan_id: null,
            draft_title: null,
            created_at: "2026-08-16T09:00:00Z",
            updated_at: "2026-08-16T09:05:00Z",
            conversation: [
              {
                message_id: "m-1",
                role: "user",
                content: "Sammanfatta det bifogade underlaget",
                timestamp: "2026-08-16T09:00:00Z"
              },
              {
                message_id: "m-2",
                role: "assistant",
                content: "",
                timestamp: "2026-08-16T09:05:00Z",
                requirements_summary: summary
              }
            ],
            attachments: [uploadedFile],
            attachment_warnings: [],
            latest_turn: null
          }
        }
      ]
    });

    await page.goto("/spaces/personal/flows/ai-builder");
    await expect(page.getByRole("navigation", { name: RAIL_LABEL })).toBeVisible({
      timeout: 20_000
    });
    await expect(page.getByRole("heading", { name: TASK_TITLE })).toBeVisible();

    await page.locator('input[type="file"]').setInputFiles({
      name: uploadedFile.name,
      mimeType: uploadedFile.mimetype,
      buffer: Buffer.from("Rapportunderlag för e2e.", "utf-8")
    });
    const chips = page.getByRole("list", { name: REFERENCE_MATERIAL });
    await expect(chips.getByTitle(uploadedFile.name)).toBeVisible({ timeout: 20_000 });

    await sendFromComposer(page, "Sammanfatta det bifogade underlaget");

    await expect(page.getByText(CONFIRM_TITLE).first()).toBeVisible({ timeout: 20_000 });
    await expect(page.getByText(CONFIRM_ATTACHMENTS)).toBeVisible();
    await expect(page.getByText(uploadedFile.name).first()).toBeVisible();

    await expect.poll(() => stub.messageRequests.length, { timeout: 20_000 }).toBe(1);
    expect(stub.messageRequests[0]?.file_ids).toEqual([uploadedFile.id]);
  });
});
