import { expect, type Page, type Route } from "@playwright/test";
import type { components } from "../src/lib/api/schema";

export const MOCK_REPLY = process.env.MOCK_REPLY ?? "E2E mock completion: pong";
export const E2E_CREDENTIALS = {
  username: process.env.E2E_USER ?? "user@example.com",
  password: process.env.E2E_PASSWORD ?? "Password1!"
};

let counter = 0;

export function uniqueName(prefix: string) {
  counter += 1;
  return `${prefix} ${Date.now()} ${counter}`;
}

export function collectAssetFailures(page: Page) {
  const failures: string[] = [];
  page.on("response", (response) => {
    const pathname = new URL(response.url()).pathname;
    if (pathname.startsWith("/assets/") && response.status() >= 400) {
      failures.push(`${response.status()} ${pathname}`);
    }
  });
  return failures;
}

/**
 * The chat stream request in either build: Next's /api/chat proxy, or the
 * backend's v3 conversations endpoint the Vite build calls directly.
 */
export function isChatStream(url: URL): boolean {
  return (
    url.pathname === "/api/chat" ||
    (url.pathname === "/api/v1/conversations/" && url.searchParams.get("version") === "3")
  );
}

/**
 * Stream fixtures forward through Playwright's API client, which has no browser
 * fetch metadata. FastAPI therefore requires a Bearer token for this write;
 * ordinary page requests still exercise the browser session cookie.
 */
export async function fetchChatStream(route: Route) {
  let headers: Record<string, string> | undefined;
  if (process.env.E2E_BASE_URL) {
    const request = route.request();
    const login = await request
      .frame()
      .page()
      .request.post(new URL("/api/v1/users/login/token/", request.url()).href, {
        form: E2E_CREDENTIALS
      });
    expect(login.status(), "Stream fixture authentication").toBe(200);
    const token: components["schemas"]["AccessToken"] = await login.json();
    headers = { ...request.headers(), authorization: `Bearer ${token.access_token}` };
  }
  const response = await route.fetch({ headers });
  expect(response.status(), "Stream fixture response").toBe(200);
  return response;
}

/** A successful API fixture belongs to the document that requested it. */
export function sessionResponseHeaders(route: Route): Record<string, string> {
  if (!process.env.E2E_BASE_URL) return {};
  const generation = route.request().headers()["eneo-session-generation"];
  if (!generation) throw new Error("Fixture request must identify its browser session");
  return { "Eneo-Session-Generation": generation };
}

/** The chat composer's accessible name ("Fråga <assistent>"). */
export const CHAT_COMPOSER_NAME = /^(Fråga|Ask) /;

/** The chat composer's text field, in either layout. */
export function chatComposer(page: Page) {
  return page.getByRole("textbox", { name: CHAT_COMPOSER_NAME });
}

export async function askChatQuestion(page: Page, question: string) {
  await chatComposer(page).fill(question);
  await page.getByRole("button", { name: /skicka meddelande|send message/i }).click();
}

/** The chat message list's accessible name. */
export const CONVERSATION_LOG_NAME = /konversation|conversation/i;

/** The chat's message list (a named log); appears once the first question is sent. */
export function conversationLog(page: Page) {
  return page.getByRole("log", { name: CONVERSATION_LOG_NAME });
}

/** An answer's activity pill ("Aktivitet: 2 steg · 1 källa"), which opens the activity panel. */
export function activityPill(page: Page) {
  return conversationLog(page).getByRole("button", { name: /^(Aktivitet|Activity):/ });
}

/** What a model that reasons and cites knowledge adds to an answer's stream. */
const ANSWER_ACTIVITY = [
  { type: "reasoning-start", id: "e2e-reasoning" },
  {
    type: "reasoning-delta",
    id: "e2e-reasoning",
    delta: "Frågan gäller testet; källan beskriver det."
  },
  { type: "reasoning-end", id: "e2e-reasoning" },
  {
    type: "source-document",
    sourceId: "e2e-source",
    mediaType: "text/plain",
    title: "E2E-källa",
    providerMetadata: { eneo: { metadata: { url: "https://example.org/e2e-kalla" } } }
  }
];

/**
 * The e2e stack's mock model answers with plain text, so its answers have no
 * activity (steps, sources) to open. This gives the page's next answers a
 * reasoning step and a cited source, as a model with reasoning and knowledge
 * would: they are added to the answer's stream (the AI SDK UI message stream
 * the backend sends) before the answer text. The backend still saves the
 * plain answer.
 */
export async function addActivityToAnswers(page: Page) {
  await page.route(isChatStream, async (route) => {
    const response = await fetchChatStream(route);
    const events = (await response.text()).split(/\r?\n\r?\n/).filter((event) => event.trim());
    const answerStart = events.findIndex((event) => /"type":\s*"(text-start|finish)"/.test(event));
    events.splice(
      answerStart === -1 ? events.length : answerStart,
      0,
      ...ANSWER_ACTIVITY.map((chunk) => `data: ${JSON.stringify(chunk)}`)
    );
    const headers = response.headers();
    await route.fulfill({
      status: response.status(),
      headers: {
        ...sessionResponseHeaders(route),
        "content-type": headers["content-type"] ?? "text/event-stream",
        "x-vercel-ai-ui-message-stream": headers["x-vercel-ai-ui-message-stream"] ?? "v1"
      },
      body: events.map((event) => `${event}\n\n`).join("")
    });
  });
}

/** Creates a shared space through the UI and returns its base path (`/spaces/<id>`). */
export async function createSpace(page: Page, name: string): Promise<string> {
  await page.goto("/spaces/list");
  // Scope to the page and the dialog: the SideNav has its own "Skapa yta".
  await page
    .getByRole("main")
    .getByRole("button", { name: /skapa yta|create space/i })
    .click();
  const dialog = page.getByRole("dialog");
  await dialog.getByLabel(/namn|name/i).fill(name);
  await dialog.getByRole("button", { name: /skapa yta|create space/i }).click();
  await page.waitForURL(/\/spaces\/[^/]+\/overview$/, { timeout: 15_000 });
  return new URL(page.url()).pathname.replace(/\/overview$/, "");
}

/**
 * On a space's knowledge page (its collections tab), opens "Skapa samling"
 * and returns the dialog once its form is shown.
 */
export async function openCreateCollectionDialog(page: Page) {
  await page
    .getByRole("main")
    .getByRole("button", { name: /skapa samling|create collection/i })
    .click();
  const dialog = page.getByRole("dialog", { name: /skapa en ny samling|create a new collection/i });
  await expect(dialog.getByLabel(/^(namn|name)$/i)).toBeVisible();
  return dialog;
}

/** Test API requests use the same transport as the selected app build. */
export function apiPath(path: string): string {
  return `${process.env.E2E_BASE_URL ? "" : "/api/eneo"}/api/v1${path}`;
}

/** JSON fixtures use the browser session owner; load an app page first. */
export async function apiRequest<T>(
  page: Page,
  path: string,
  options: { method?: "GET" | "POST" | "PATCH"; body?: object } = {}
): Promise<T> {
  // Cookie-authenticated writes require the browser's same-origin fetch metadata.
  const response = await page.evaluate(
    async ({ url, options, browserSession }) => {
      const headers = new Headers();
      if (options.body !== undefined) headers.set("content-type", "application/json");
      if (browserSession) {
        const session = await fetch("/api/v1/auth/session/");
        const generation = session.headers.get("Eneo-Session-Generation");
        if (session.status !== 204 || !generation)
          throw new Error(`Fixture session probe failed (${session.status})`);
        headers.set("Eneo-Session-Generation", generation);
      }
      const response = await fetch(url, {
        method: options.method ?? "GET",
        headers,
        body: options.body === undefined ? undefined : JSON.stringify(options.body)
      });
      return { ok: response.ok, body: await response.text() };
    },
    { url: apiPath(path), options, browserSession: Boolean(process.env.E2E_BASE_URL) }
  );
  expect(response.ok, response.body).toBe(true);
  return JSON.parse(response.body);
}

/** A same-origin write returning the created resource's id. */
export async function apiPost(page: Page, path: string, data: object): Promise<string> {
  return (await apiPostJson<{ id: string }>(page, path, data)).id;
}

/** The same browser-session write for endpoints returning a result rather than a resource id. */
export async function apiPostJson<T>(page: Page, path: string, data: object): Promise<T> {
  return apiRequest<T>(page, path, { method: "POST", body: data });
}

/**
 * A new shared space with an assistant, an app and a text run of it. The e2e
 * stack runs no worker, so the run stays queued: its result page is pending.
 */
export async function spaceWithWork(page: Page, name: string) {
  await page.goto("/spaces/list");
  const spaceId = await apiPost(page, "/spaces/", { name });
  const assistant = await apiPost(page, `/spaces/${spaceId}/applications/assistants/`, {
    name: uniqueName("Bygglov")
  });
  const app = await apiPost(page, `/spaces/${spaceId}/applications/apps/`, {
    name: uniqueName("Protokoll")
  });
  const run = await apiPost(page, `/apps/${app}/runs/`, {
    text: "Sammanfatta protokollet",
    files: []
  });
  const space = `/spaces/${spaceId}`;
  return {
    space,
    editor: `${space}/assistants/${assistant}/edit`,
    result: `${space}/apps/${app}/results/${run}`,
    app: `${space}/apps/${app}`,
    appEditor: `${space}/apps/${app}/edit`,
    dashboardApp: `/dashboard/app/${app}`,
    dashboardResult: `/dashboard/app/${app}/results/${run}`
  };
}

/**
 * The audit logs, past their gate: a justified access session. The backend
 * allows five an hour, so a run opens as few as it can.
 */
export async function auditLogs(page: Page) {
  await page.goto("/admin/audit-logs");
  const table = page.getByRole("table", { name: "Granskningsloggar" });
  const gate = page.getByRole("combobox", { name: "Åtkomstskäl" });
  await expect(table.or(gate)).toBeVisible();
  if (await gate.isVisible()) {
    await gate.click();
    await page.getByRole("option").first().click();
    await expect(page.getByRole("listbox")).toBeHidden();
    const reason = page.getByLabel("Detaljerad motivering");
    await reason.fill("Granskning av responsiva tabeller i testmiljön.");
    await expect(reason).toHaveValue("Granskning av responsiva tabeller i testmiljön.");
    await page.getByRole("button", { name: "Få åtkomst till loggar" }).click();
  }
  await expect(table).toBeVisible();
  return { table, region: page.getByRole("group", { name: "Granskningsloggar" }) };
}
