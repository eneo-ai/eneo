import { expect, test, type APIRequestContext, type Locator, type Page } from "@playwright/test";
import { backendFetch, expectOk, MOCK_REPLY, uniqueName } from "./helpers";

type BackendFetchOptions = Parameters<typeof backendFetch>[3];

type ApiRecord = Record<string, unknown>;

type CreatedFlow = {
  id: string;
  name: string;
  publishedVersion: number | null;
};

type CreatedAssistant = {
  id: string;
};

type FlowStepSetup = {
  step_order: number;
  user_description: string;
  input_source: "flow_input" | "previous_step";
  input_type: "text";
  output_mode: "pass_through" | "render_verbatim";
  output_type: "text" | "pdf";
  review_policy?: { mode: "view" };
};

const RUN_FLOW_LABEL = /^(Run flow|Kör flöde)$/;
const RUN_INPUT_LABEL = /^(Input|Indata)$/;
const NEXT_LABEL = /^(Next|Nästa)$/;
const START_RUN_LABEL = /^(Start run|Starta körning)$/;
const REVIEW_CHECKPOINT_LABEL = /^(Review checkpoint|Granskningspunkt)$/;
const APPROVE_LABEL = /^(Approve|Godkänn)$/;
const RESUME_LABEL = /^(Resume|Fortsätt)$/;
const DOWNLOAD_PDF_LABEL = /^(Download|Ladda ner) .*\.pdf$/;

function expectApiRecord(value: unknown, context: string): asserts value is ApiRecord {
  if (value === null || typeof value !== "object" || Array.isArray(value)) {
    throw new Error(`${context} should return an object`);
  }
}

function requiredString(record: ApiRecord, key: string, context: string): string {
  const value = record[key];
  if (typeof value !== "string") {
    throw new Error(`${context}.${key} should be a string`);
  }
  return value;
}

function nullableNumber(record: ApiRecord, key: string, context: string): number | null {
  const value = record[key];
  if (value === null || value === undefined) return null;
  if (typeof value !== "number") {
    throw new Error(`${context}.${key} should be a number or null`);
  }
  return value;
}

function parseFlow(value: unknown, context: string): CreatedFlow {
  expectApiRecord(value, context);
  return {
    id: requiredString(value, "id", context),
    name: requiredString(value, "name", context),
    publishedVersion: nullableNumber(value, "published_version", context)
  };
}

function parseAssistant(value: unknown, context: string): CreatedAssistant {
  expectApiRecord(value, context);
  return { id: requiredString(value, "id", context) };
}

async function apiJson(
  page: Page,
  request: APIRequestContext,
  path: string,
  options: BackendFetchOptions,
  context: string
): Promise<unknown> {
  const response = await backendFetch(page, request, path, options);
  await expectOk(response, context);
  return response.json();
}

async function createPublishedFlow(
  page: Page,
  request: APIRequestContext,
  name: string,
  description: string,
  steps: FlowStepSetup[]
): Promise<CreatedFlow> {
  const personalSpace = await apiJson(
    page,
    request,
    "/api/v1/spaces/type/personal/",
    {},
    "loading personal space"
  );
  expectApiRecord(personalSpace, "personal space");
  const spaceId = requiredString(personalSpace, "id", "personal space");

  const draftFlow = parseFlow(
    await apiJson(
      page,
      request,
      "/api/v1/flows/",
      {
        method: "POST",
        data: { space_id: spaceId, name, description, steps: [] }
      },
      "creating draft flow"
    ),
    "draft flow"
  );

  const assistant = parseAssistant(
    await apiJson(
      page,
      request,
      `/api/v1/flows/${draftFlow.id}/assistants/`,
      {
        method: "POST",
        data: { name: uniqueName("E2E Flow assistant") }
      },
      "creating flow-managed assistant"
    ),
    "flow-managed assistant"
  );

  await apiJson(
    page,
    request,
    `/api/v1/flows/${draftFlow.id}/`,
    {
      method: "PATCH",
      data: {
        steps: steps.map((step) => ({ ...step, assistant_id: assistant.id }))
      }
    },
    "adding flow steps"
  );

  const publishedFlow = parseFlow(
    await apiJson(
      page,
      request,
      `/api/v1/flows/${draftFlow.id}/publish/`,
      { method: "POST" },
      "publishing flow"
    ),
    "published flow"
  );
  if (publishedFlow.publishedVersion === null) {
    throw new Error("published flow should include a published version");
  }
  return publishedFlow;
}

async function startRunFromWizard(page: Page, flow: CreatedFlow, input: string) {
  await page.goto("/spaces/personal/flows");
  await page.getByRole("link", { name: flow.name, exact: true }).click();

  await expect(page).toHaveURL(new RegExp(`/spaces/personal/flows/${flow.id}`));
  await page.getByRole("button", { name: RUN_FLOW_LABEL }).click();

  const dialog = page.getByRole("dialog", { name: RUN_FLOW_LABEL });
  await dialog.getByRole("textbox", { name: RUN_INPUT_LABEL }).fill(input);
  await dialog.getByRole("button", { name: NEXT_LABEL }).click();
  await dialog.getByRole("button", { name: START_RUN_LABEL }).click();

  const historyPanel = page.locator("#panel-history");
  await expect(historyPanel).toBeVisible();
  const runTable = historyPanel.getByRole("table");
  const evidenceToggle = runTable.getByTestId(/^flow-run-evidence-toggle-/);
  await expect(evidenceToggle).toBeVisible();
  return { runTable, evidenceToggle };
}

async function expandedRunPanel(page: Page, evidenceToggle: Locator): Promise<Locator> {
  if ((await evidenceToggle.getAttribute("aria-expanded")) !== "true") {
    await evidenceToggle.click();
  }
  await expect(evidenceToggle).toHaveAttribute("aria-expanded", "true");

  const panelId = await evidenceToggle.getAttribute("aria-controls");
  if (!panelId) throw new Error("run evidence toggle should control a visible panel");
  const panel = page.getByRole("table").locator(`#${panelId}`);
  await expect(panel).toBeVisible();
  return panel;
}

test("the run wizard produces and downloads a PDF artifact", async ({ page, request }) => {
  test.setTimeout(120_000);
  await page.goto("/");

  const flow = await createPublishedFlow(
    page,
    request,
    uniqueName("E2E PDF Flow"),
    "Deterministic browser PDF artifact Flow",
    [
      {
        step_order: 1,
        user_description: "Create deterministic content",
        input_source: "flow_input",
        input_type: "text",
        output_mode: "pass_through",
        output_type: "text"
      },
      {
        step_order: 2,
        user_description: "Render deterministic PDF",
        input_source: "previous_step",
        input_type: "text",
        output_mode: "render_verbatim",
        output_type: "pdf"
      }
    ]
  );

  const { runTable, evidenceToggle } = await startRunFromWizard(
    page,
    flow,
    uniqueName("PDF run input")
  );

  const evidencePanel = await expandedRunPanel(page, evidenceToggle);
  await expect(evidencePanel).toContainText(MOCK_REPLY, { timeout: 60_000 });

  const downloadButton = runTable.getByRole("button", { name: DOWNLOAD_PDF_LABEL });
  await expect(downloadButton).toBeVisible();
  const downloadPromise = page.waitForEvent("download");
  await downloadButton.click();
  const download = await downloadPromise;
  expect(download.suggestedFilename()).toBe("step_2_output.pdf");
  expect(await download.failure()).toBeNull();
});

test("a visible review checkpoint can be approved and resumed", async ({ page, request }) => {
  test.setTimeout(120_000);
  await page.goto("/");

  const flow = await createPublishedFlow(
    page,
    request,
    uniqueName("E2E Review Flow"),
    "Deterministic browser review checkpoint Flow",
    [
      {
        step_order: 1,
        user_description: "Create content for visible review",
        input_source: "flow_input",
        input_type: "text",
        output_mode: "pass_through",
        output_type: "text",
        review_policy: { mode: "view" }
      }
    ]
  );

  const { runTable, evidenceToggle } = await startRunFromWizard(
    page,
    flow,
    uniqueName("review run input")
  );
  const reviewPanel = await expandedRunPanel(page, evidenceToggle);
  await expect(reviewPanel.getByRole("heading", { name: REVIEW_CHECKPOINT_LABEL })).toBeVisible({
    timeout: 60_000
  });

  await reviewPanel.getByRole("button", { name: APPROVE_LABEL }).click();
  const resumeButton = reviewPanel.getByRole("button", { name: RESUME_LABEL });
  await expect(resumeButton).toBeEnabled();
  await resumeButton.click();

  const terminalPanel = await expandedRunPanel(page, evidenceToggle);
  await expect(terminalPanel).toContainText(MOCK_REPLY, { timeout: 60_000 });
});
