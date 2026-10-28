import { expect, type Page } from "@playwright/test";

export const MOCK_REPLY = process.env.MOCK_REPLY ?? "E2E mock completion: pong";

let counter = 0;

export function uniqueName(prefix: string) {
  counter += 1;
  return `${prefix} ${Date.now()} ${counter}`;
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
    const response = await route.fetch();
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

/**
 * A write through the app's API proxy, which accepts writes from the app's
 * own origin only; returns the created resource's id. The page must have
 * loaded an app page first (its URL is the origin).
 */
export async function apiPost(page: Page, path: string, data: object): Promise<string> {
  const response = await page.request.post(`/api/eneo/api/v1${path}`, {
    data,
    headers: { origin: new URL(page.url()).origin }
  });
  expect(response.ok(), await response.text()).toBe(true);
  return ((await response.json()) as { id: string }).id;
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
    result: `${space}/apps/${app}/results/${run}`
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
