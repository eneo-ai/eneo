import type { Browser, BrowserContextOptions, Page } from "@playwright/test";
import { STORAGE_STATE } from "../playwright.config";
import { watchCsp } from "./csp";
import { apiPost, spaceWithWork, uniqueName } from "./helpers";
import { ROUTES, type Fixtures } from "./responsive-routes";

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
  const spaceName = uniqueName(prefix);
  const work = await spaceWithWork(page, spaceName);
  const spaceId = work.space.split("/").pop()!;
  const groupChatName = uniqueName("Grupp");
  const groupChat = await apiPost(page, `${work.space}/applications/group-chats/`, {
    name: groupChatName
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
    spaceName,
    assistant: work.editor.split("/assistants/")[1]!.split("/")[0]!,
    app: work.app.split("/apps/")[1]!,
    run: work.result.split("/results/")[1]!,
    groupChat,
    groupChatName,
    website,
    collection,
    userId
  };
}

/**
 * The device a walk's viewport stands for, named by its first word. CI splits each walk
 * over its legs by walk tag and device (".github/workflows/ci.yml" greps "@a11y-routes @ipad"),
 * so a viewport whose name starts with none of these has no leg: it fails here.
 */
export const DEVICE_GROUPS = ["phone", "ipad", "desktop"] as const;

/** A walk test's tags: the walk's own, then its device's, in the order the legs grep them. */
export function walkTags(walk: `@${string}`, viewport: string): string[] {
  const device = DEVICE_GROUPS.find((group) => viewport.startsWith(group));
  if (!device) throw new Error(`${viewport}: no device group in DEVICE_GROUPS`);
  return [walk, `@${device}`];
}

export type Walk = {
  baseURL: string | undefined;
  fixtures: Fixtures;
  /** What the walk's signed-in and signed-out contexts both open with. */
  context: BrowserContextOptions;
  /** A regular expression that narrows the walk to some route patterns. */
  only?: string;
};

/**
 * Opens every screen of tests/responsive-routes.ts, signed in or out as its entry says, and
 * runs `visit` on each. Returns what `visit` objected to, each screen that did not open and
 * what the Content-Security-Policy blocked: its contexts are not the test's, so the CSP
 * fixture of tests/csp.ts cannot see them.
 */
export async function walkRoutes(
  browser: Browser,
  { baseURL, fixtures, context, only }: Walk,
  visit: (page: Page, pattern: string, signedIn: boolean) => Promise<string[]>
) {
  const contexts = {
    in: await browser.newContext({ ...context, baseURL, storageState: STORAGE_STATE }),
    out: await browser.newContext({
      ...context,
      baseURL,
      storageState: { cookies: [], origins: [] }
    })
  };
  const violations: string[] = [];
  for (const context of Object.values(contexts)) await watchCsp(context, violations);
  const pages = { in: await contexts.in.newPage(), out: await contexts.out.newPage() };
  const problems: string[] = [];
  for (const [pattern, entry] of Object.entries(ROUTES)) {
    if ("skip" in entry) continue;
    if (only && !new RegExp(only).test(pattern)) continue;
    const signedIn = entry.auth !== "out";
    const page = pages[signedIn ? "in" : "out"];
    try {
      await openRoute(page, entry.url(fixtures), signedIn);
    } catch (error) {
      problems.push(`${pattern}: did not open (${String(error).split("\n")[0]})`);
      continue;
    }
    problems.push(...(await visit(page, pattern, signedIn)));
    problems.push(...violations.splice(0).map((violation) => `${pattern}: CSP ${violation}`));
  }
  for (const context of Object.values(contexts)) await context.close();
  return problems;
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
