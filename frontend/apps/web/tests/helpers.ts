import { expect, type APIRequestContext, type Page } from "@playwright/test";

export const BACKEND_URL = process.env.E2E_BACKEND_URL ?? "http://127.0.0.1:8124";
export const MOCK_REPLY = "E2E mock completion: pong";

let counter = 0;

export function uniqueName(prefix: string) {
  counter += 1;
  return `${prefix} ${Date.now()} ${counter}`;
}

export async function getAuthToken(page: Page) {
  const cookies = await page.context().cookies();
  const authCookie = cookies.find((cookie) => cookie.name === "auth");
  expect(
    authCookie,
    "expected authenticated browser context to contain the auth cookie"
  ).toBeTruthy();
  return authCookie!.value;
}

type FetchOptions = Parameters<APIRequestContext["fetch"]>[1];

export async function backendFetch(
  page: Page,
  request: APIRequestContext,
  path: string,
  options: FetchOptions = {}
) {
  const token = await getAuthToken(page);
  const headers = {
    Authorization: `Bearer ${token}`,
    ...((options.headers as Record<string, string> | undefined) ?? {})
  };

  return request.fetch(`${BACKEND_URL}${path}`, {
    ...options,
    headers
  });
}

export async function expectOk(
  response: Awaited<ReturnType<APIRequestContext["fetch"]>>,
  context: string
) {
  if (response.ok()) return;
  throw new Error(
    `${context} failed with ${response.status()} ${response.statusText()}: ${await response.text()}`
  );
}

/**
 * The flow's draft revision as the backend holds it now. Writing a flow-managed
 * assistant advances the flow's revision, so a fence taken when the flow was
 * created is stale once its steps' assistants have been edited.
 */
export async function currentDraftRevision(
  page: Page,
  request: APIRequestContext,
  flowId: string
): Promise<number> {
  const response = await backendFetch(page, request, `/api/v1/flows/${flowId}/`);
  await expectOk(response, "reading the flow's draft revision");
  const flow: { draft_revision: number } = await response.json();
  return flow.draft_revision;
}

const READY_BUILDER_MODEL_ID = "00000000-0000-0000-0000-0000000000e2";

/**
 * A Builder model listing with one ready model as the default. The composer
 * sends only when the model it shows is listed and ready, so a stub that lists
 * no model keeps the send button disabled.
 */
export function readyBuilderModelsBody() {
  return {
    models: [
      {
        id: READY_BUILDER_MODEL_ID,
        name: "E2E Mock",
        provider: "openai",
        org: "OpenAI",
        provider_name: "E2E",
        reasoning_effort_options: [],
        availability: { state: "ready" }
      }
    ],
    default_model_id: READY_BUILDER_MODEL_ID
  };
}

export async function askChatQuestion(page: Page, question: string) {
  const input = page.locator('[contenteditable="true"]').first();
  await input.click();
  await input.press("ControlOrMeta+A");
  await input.press("Backspace");
  await input.pressSequentially(question);
  await page.locator('button[name="ask"]').click();
}

export async function loginViaUi(page: Page, email: string, password: string) {
  await page.goto("/login");
  await page.locator('input[name="email"]').fill(email);
  await page.locator('input[name="password"]').fill(password);
  await page.locator('button[type="submit"]').click();
  await page.waitForURL((url) => !url.pathname.startsWith("/login"), { timeout: 15_000 });
  await expect(page).not.toHaveURL(/\/login/);
}
