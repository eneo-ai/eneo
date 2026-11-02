import type { Browser, Page } from "@playwright/test";
import { STORAGE_STATE } from "../playwright.config";
import type { Schema } from "../src/lib/api/models";
import { apiPost, apiRequest, spaceWithWork, uniqueName } from "./helpers";
import type { Fixtures } from "./responsive-routes";

/**
 * What the screens that need a record are opened with: a shared space with an
 * assistant, an app and a run, plus a group chat, a website, a collection and
 * a published flow with a finished run. Created once per run; ROUTES
 * (tests/responsive-routes.ts) points at them.
 */
export async function createFixtures(
  browser: Browser,
  baseURL: string | undefined,
  prefix: string
): Promise<Fixtures> {
  const context = await browser.newContext({ storageState: STORAGE_STATE, baseURL });
  const page = await context.newPage();
  const work = await spaceWithWork(page, uniqueName(prefix));
  const spaceId = work.space.split("/").pop()!;
  const groupChat = await apiPost(page, `${work.space}/applications/group-chats/`, {
    name: uniqueName("Grupp")
  });
  const website = await apiPost(page, `/spaces/${spaceId}/knowledge/websites/`, {
    url: "https://example.org/contract",
    name: "Kontraktsida",
    crawl_type: "crawl",
    update_interval: "never",
    download_files: false
  });
  const detail = await page.evaluate(
    async (id) => (await fetch(`/api/v1/spaces/${id}/`)).json(),
    spaceId
  );
  const embedding = detail.embedding_models?.[0]?.id as string | undefined;
  const collection = await apiPost(page, `/spaces/${spaceId}/knowledge/groups/`, {
    name: uniqueName("Samling"),
    embedding_model: embedding ? { id: embedding } : undefined
  });
  const flow = await finishedFlowRun(
    page,
    spaceId,
    (detail.completion_models as { id: string; name: string }[]).find(
      (model) => model.name === "e2e-mock"
    )?.id ?? detail.completion_models[0].id
  );
  // A key, so the tables of /admin/api-keys and /account/api-keys have a row to measure.
  await apiPost(page, "/api-keys", {
    name: uniqueName("Kontrollnyckel"),
    key_type: "sk_",
    permission: "read",
    scope_type: "tenant"
  });
  // The release notice above the chat's lists shows once (the release is then
  // announced) and is gone from the next visit on: on a fresh database it would be in the
  // first run's measurements and not in the second's. Seen and announced here, it never shows.
  await page.goto("/whats-new");
  await page.waitForSelector("main#main-content", { state: "visible", timeout: 15_000 });
  await page.waitForTimeout(1_000);
  await page.goto("/spaces/personal/chat");
  await page.waitForSelector("main#main-content", { state: "visible", timeout: 15_000 });
  await page.waitForTimeout(1_500);
  const userId = await page.evaluate(
    async () => (await (await fetch("/api/v1/users/me/")).json()).id
  );
  await context.close();
  return {
    space: work.space,
    assistant: work.editor.split("/assistants/")[1]!.split("/")[0]!,
    app: work.app.split("/apps/")[1]!,
    run: work.result.split("/results/")[1]!,
    groupChat,
    website,
    collection,
    flow: flow.flowId,
    flowRun: flow.runId,
    userId
  };
}

/**
 * A published one-step flow and a run of it that has finished, so its pages show their
 * settled layout (a run still working would change under the measurement).
 */
async function finishedFlowRun(page: Page, spaceId: string, completionModel: string) {
  const created = await apiRequest<Schema<"FlowPublic">>(page, "/flows/", {
    method: "POST",
    body: { space_id: spaceId, name: uniqueName("Flöde") } satisfies Schema<"FlowCreateRequest">
  });
  const saved = await apiRequest<Schema<"FlowPublic">>(page, `/flows/${created.id}/editor/`, {
    method: "PATCH",
    body: {
      expected_revision: created.draft_revision,
      definition: {},
      new_steps: [
        {
          name: "Sammanfatta underlag",
          assistant: {
            completion_model: { id: completionModel },
            prompt: { text: "Sammanfatta underlaget." }
          },
          configuration: {
            input_source: "flow_input",
            input_type: "text",
            output_mode: "pass_through",
            output_type: "text"
          }
        }
      ]
    } satisfies Schema<"FlowEditorUpdateRequest">
  });
  const flow = await apiRequest<Schema<"FlowPublic">>(
    page,
    `/flows/${created.id}/publish/?expected_revision=${saved.draft_revision}`,
    { method: "POST" }
  );
  const run = await apiRequest<Schema<"FlowRunPublic">>(page, `/flows/${flow.id}/runs/`, {
    method: "POST",
    body: {
      expected_flow_version: flow.published_version,
      run_label: uniqueName("Körning"),
      input_payload_json: { text: "Ett kort underlag för kontraktet." }
    } satisfies Schema<"FlowRunCreateRequest">
  });
  const status = `/flows/${flow.id}/runs/${run.id}/status/`;
  for (let attempt = 0; attempt < 60; attempt++) {
    const summary = await apiRequest<Schema<"FlowRunSummaryPublic">>(page, status);
    if (summary.status === "completed") return { flowId: flow.id, runId: run.id };
    if (summary.status === "failed" || summary.status === "cancelled")
      throw new Error(`The contract's flow run ended ${summary.status}`);
    await page.waitForTimeout(1_000);
  }
  throw new Error("The contract's flow run did not finish within 60 s");
}

/** Opens a route and waits until it shows its content and has stopped loading. */
export async function openRoute(page: Page, url: string, signedIn: boolean) {
  await page.goto(url);
  await page.waitForSelector(signedIn ? "main#main-content" : "main, h1", {
    state: "visible",
    timeout: 15_000
  });
  await page
    .waitForFunction(() => !document.querySelector('main [aria-busy="true"]'), undefined, {
      timeout: 8_000
    })
    .catch(() => {});
  await page.waitForTimeout(400);
}

/**
 * What happens to a page's document while a sweep is on one route. A sweep's
 * `evaluate` dies with "Execution context was destroyed" when the page leaves
 * its document on its own (a session refusal, a chunk reload, a hand-off); the
 * bare error names neither the screen nor the cause. `begin` after the route
 * has opened, `explain` for the error: it names the route and what the page
 * did since (navigations, refused or failed requests, a changed session
 * generation, a chunk that failed to load, console errors).
 */
export function watchDocument(page: Page) {
  const events: string[] = [];
  let route = "";
  let watching = false;
  const note = (what: string) => {
    if (watching) events.push(`${new Date().toISOString().slice(11, 23)} ${what}`);
  };
  page.on("framenavigated", (frame) => {
    if (frame === page.mainFrame()) note(`navigated to ${frame.url()}`);
  });
  // A changed session generation sends the app to sign in again, whatever the status was.
  let generation: string | undefined;
  page.on("response", (response) => {
    const { pathname } = new URL(response.url());
    const ours = pathname.startsWith("/api/") || pathname.startsWith("/assets/");
    if (ours && response.status() >= 400) note(`${response.status()} ${pathname}`);
    if (pathname.startsWith("/api/")) {
      const next = response.headers()["eneo-session-generation"];
      if (next !== undefined && generation !== undefined && next !== generation)
        note(`session generation changed on ${pathname}`);
      if (next !== undefined) generation = next;
    }
  });
  // A route chunk that fails to load reloads the page (chunk recovery).
  page
    .addInitScript(() => {
      window.addEventListener("vite:preloadError", (event) => {
        const payload = (event as Event & { payload?: { message?: string } }).payload;
        console.error(`vite:preloadError ${payload?.message ?? ""}`);
      });
    })
    .catch(() => {});
  page.on("requestfailed", (request) => {
    const { pathname } = new URL(request.url());
    const reason = request.failure()?.errorText ?? "failed";
    // A request a navigation or a closed stream cuts off is not a failure of the server.
    if (reason === "net::ERR_ABORTED") return;
    if (pathname.startsWith("/api/") || pathname.startsWith("/assets/"))
      note(`${reason} ${pathname}`);
  });
  page.on("console", (message) => {
    if (message.type() === "error") note(`console: ${message.text().slice(0, 160)}`);
  });
  return {
    begin(pattern: string) {
      route = pattern;
      events.length = 0;
      watching = true;
    },
    explain(error: unknown) {
      watching = false;
      const seen = events.length > 0 ? events.join("\n  ") : "nothing seen";
      return new Error(
        `${route}: ${String(error).split("\n")[0]}\n  since the route opened:\n  ${seen}`,
        { cause: error }
      );
    }
  };
}
