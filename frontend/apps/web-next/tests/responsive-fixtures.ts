import type { Browser, Page } from "@playwright/test";
import { STORAGE_STATE } from "../playwright.config";
import { apiPost, spaceWithWork, uniqueName } from "./helpers";
import type { Fixtures } from "./responsive-routes";

/**
 * What the screens that need a record are opened with: a shared space with an
 * assistant, an app and a run, plus a group chat, a website and a collection.
 * Created once per run; ROUTES (tests/responsive-routes.ts) points at them.
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
  const assistant = work.editor.split("/assistants/")[1]!.split("/")[0]!;
  // A real draft and house-style template, so both widget editors show their fields.
  await apiPost(page, `/spaces/${spaceId}/widgets/`, {
    name: uniqueName("Widget"),
    target_id: assistant
  });
  const widgetTemplate = await apiPost(page, "/admin/widget-templates/", {
    name: uniqueName("Widgetmall")
  });
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
  // A key, so the lists of /admin/api-keys and /account/api-keys have a row to measure.
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
    assistant,
    app: work.app.split("/apps/")[1]!,
    run: work.result.split("/results/")[1]!,
    groupChat,
    website,
    collection,
    userId,
    widgetTemplate
  };
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
