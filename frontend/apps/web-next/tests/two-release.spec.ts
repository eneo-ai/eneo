import { execFile } from "node:child_process";
import { promisify } from "node:util";
import type { Page, TestInfo } from "@playwright/test";
import { expect, test } from "./csp";
import {
  askChatQuestion,
  chatComposer,
  conversationLog,
  E2E_CREDENTIALS,
  MOCK_REPLY
} from "./helpers";

const swapCommand = process.env.TWO_RELEASE_SWAP_CMD;
const run = promisify(execFile);

test.skip(!swapCommand, "Requires two production builds and a local server-swap executable.");
test.use({ storageState: { cookies: [], origins: [] }, actionTimeout: 10_000 });
test.setTimeout(120_000);

async function swap(release: "A" | "B") {
  if (!swapCommand) throw new Error("TWO_RELEASE_SWAP_CMD is required");
  // A path and positional arguments, never a shell command or credentials.
  await run(swapCommand, [release], { timeout: 90_000 });
}

test.beforeEach(async ({ page }) => {
  await swap("A");
  await page.goto("/login?showUsernameAndPassword=true&next=%2Fspaces%2Fpersonal%2Fchat");
  await page.locator('input[name="email"]').fill(E2E_CREDENTIALS.username);
  await page.locator('input[name="password"]').fill(E2E_CREDENTIALS.password);
  await page.locator('button[type="submit"]').click();
  await expect(chatComposer(page)).toBeVisible();
});

function observeDeployment(page: Page) {
  const missing: string[] = [];
  const revisions: string[] = [];
  let reloads = 0;
  page.on("request", (request) => {
    if (request.isNavigationRequest() && request.frame() === page.mainFrame()) reloads++;
  });
  page.on("response", async (response) => {
    const path = new URL(response.url()).pathname;
    if (path.endsWith(".js") && response.status() === 404) missing.push(path);
    if (path === "/api/v1/runtime-config" && response.ok()) {
      revisions.push((await response.json()).revision);
    }
  });
  return {
    missing,
    revisions,
    reloads: () => reloads,
    async record(info: TestInfo) {
      await info.attach("deployment-observation", {
        contentType: "application/json",
        body: JSON.stringify({ missing, revisions, reloads }, null, 2)
      });
    }
  };
}

async function prepareUsersNavigation(page: Page) {
  await page.getByRole("button", { name: "Sök", exact: true }).click();
  const palette = page.getByRole("dialog", { name: /^(Sök i Eneo|Search Eneo)$/ });
  await palette.getByRole("combobox").fill("Användare");
  const users = palette.getByRole("option", { name: "Administration › Användare", exact: true });
  await expect(users).toBeVisible();
  return users;
}

test("an unvisited route opens the replacement release", async ({ page }, info) => {
  const users = await prepareUsersNavigation(page);
  const observed = observeDeployment(page);
  try {
    await swap("B");
    await users.click();
    await expect(page.getByRole("heading", { name: "Users release B", exact: true })).toBeVisible();
    expect(observed.reloads()).toBeLessThanOrEqual(1);
    expect(observed.missing.length).toBeGreaterThan(0);
    expect(observed.revisions).toContain("release-B");
  } finally {
    await observed.record(info);
  }
});

for (const saved of [false, true]) {
  test(`staying in ${saved ? "a saved" : "a new"} conversation keeps the draft; leaving confirms recovery once`, async ({
    page
  }, info) => {
    if (saved) {
      await askChatQuestion(page, "An existing conversation for deployment recovery");
      await expect(conversationLog(page).getByText(MOCK_REPLY)).toBeVisible();
      await expect(page).toHaveURL(/session_id=/);
    }
    const originalUrl = page.url();
    const draft = "En fråga som inte har skickats";
    await chatComposer(page).fill(draft);
    const users = await prepareUsersNavigation(page);
    const observed = observeDeployment(page);
    const nativePrompts: string[] = [];
    page.on("dialog", async (dialog) => {
      nativePrompts.push(dialog.type());
      await dialog.dismiss();
    });
    try {
      await swap("B");
      await users.click();
      const confirmation = page.getByRole("alertdialog", { name: "Lämna chatten?", exact: true });
      await expect(confirmation).toBeVisible();
      await confirmation.getByRole("button", { name: "Avbryt", exact: true }).click();
      // Allow pending UI work to settle: Stay must preserve the usable page, not one transient frame.
      await page.waitForTimeout(1_000);
      await expect(page).toHaveURL(originalUrl);
      await expect(chatComposer(page)).toBeVisible();
      await expect(chatComposer(page)).toBeEditable();
      await expect(chatComposer(page)).toHaveValue(draft);
      expect(observed.reloads()).toBe(0);
      expect(observed.missing).toEqual([]);
      await chatComposer(page).fill(draft + " och en fortsättning");

      await (await prepareUsersNavigation(page)).click();
      await confirmation.getByRole("button", { name: "Lämna chatten", exact: true }).click();
      await expect(
        page.getByRole("heading", { name: "Users release B", exact: true })
      ).toBeVisible();
      await expect(
        page.getByRole("button", { name: /skapa användare|create user/i })
      ).toBeEnabled();
      expect(nativePrompts).toEqual([]);
      expect(observed.reloads()).toBe(1);
      expect(observed.missing.length).toBeGreaterThan(0);
      expect(observed.revisions).toContain("release-B");
    } finally {
      await observed.record(info);
    }
  });
}

test("a lazy feature in an open conversation survives replacement", async ({
  page,
  context
}, info) => {
  await context.grantPermissions(["clipboard-read", "clipboard-write"]);
  await askChatQuestion(page, "Two-release clipboard proof");
  await expect(conversationLog(page).getByText(MOCK_REPLY)).toBeVisible();
  await expect(page).toHaveURL(/session_id=/);
  const saved = page.url();
  const observed = observeDeployment(page);
  async function copy() {
    await conversationLog(page)
      .getByRole("button", { name: /fler åtgärder|more actions/i })
      .click();
    await page.getByRole("menuitem", { name: /kopiera som rich text|copy as rich text/i }).click();
  }
  try {
    await swap("B");
    await copy();
    await expect.poll(() => observed.reloads()).toBe(1);
    await expect(page).toHaveURL(saved);
    await expect(conversationLog(page).getByText(MOCK_REPLY)).toBeVisible();
    await copy();
    await expect
      .poll(() => page.evaluate(() => navigator.clipboard.readText()))
      .toContain("release B");
    expect(observed.revisions).toContain("release-B");
    expect(observed.missing.length).toBeGreaterThan(0);
    expect(observed.reloads()).toBeLessThanOrEqual(1);
  } finally {
    await observed.record(info);
  }
});
