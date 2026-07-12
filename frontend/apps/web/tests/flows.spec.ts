import { expect, test, type APIRequestContext, type Page } from "@playwright/test";
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

type CreatedRun = {
  id: string;
};

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

function parseRun(value: unknown, context: string): CreatedRun {
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

test("a published Flow can be listed, opened, and show a worker-backed run result", async ({
  page,
  request
}) => {
  test.setTimeout(120_000);

  const flowName = uniqueName("E2E Flow smoke");
  const stepName = "Mock completion";
  const runInput = uniqueName("worker-backed flow input");

  await page.goto("/");

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
        data: {
          space_id: spaceId,
          name: flowName,
          description: "Deterministic browser smoke Flow",
          steps: []
        }
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
        steps: [
          {
            assistant_id: assistant.id,
            step_order: 1,
            user_description: stepName,
            input_source: "flow_input",
            input_type: "text",
            output_mode: "pass_through",
            output_type: "text"
          }
        ]
      }
    },
    "adding flow step"
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

  const run = parseRun(
    await apiJson(
      page,
      request,
      `/api/v1/flows/${publishedFlow.id}/runs/`,
      {
        method: "POST",
        data: {
          expected_flow_version: publishedFlow.publishedVersion,
          input_payload_json: { text: runInput }
        }
      },
      "creating flow run"
    ),
    "flow run"
  );

  await page.goto("/spaces/personal/flows");
  const flowLink = page.getByRole("link", { name: flowName, exact: true });
  await expect(flowLink).toBeVisible();
  await flowLink.click();

  await expect(page).toHaveURL(new RegExp(`/spaces/personal/flows/${publishedFlow.id}`));
  await expect(page.getByRole("heading", { name: flowName, exact: true })).toBeVisible();

  await page.locator("#flow-detail-tab-history").click();
  await expect(page.locator("#panel-history")).toBeVisible();

  const evidenceButton = page.getByTestId(`flow-run-evidence-toggle-${run.id}`);
  await expect(evidenceButton).toBeVisible({ timeout: 30_000 });
  if ((await evidenceButton.getAttribute("aria-expanded")) !== "true") {
    await evidenceButton.click();
  }
  await expect(evidenceButton).toHaveAttribute("aria-expanded", "true");

  // Desktop and mobile evidence containers currently share this id; scope to the
  // desktop table rendered for the E2E viewport.
  const evidencePanel = page.getByRole("table").locator(`#flow-run-evidence-${run.id}`);
  await expect(evidencePanel).toContainText(MOCK_REPLY, { timeout: 60_000 });
});
