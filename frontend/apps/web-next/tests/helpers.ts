import { expect, type Page } from "@playwright/test";

export const MOCK_REPLY = process.env.MOCK_REPLY ?? "E2E mock completion: pong";

let counter = 0;

export function uniqueName(prefix: string) {
  counter += 1;
  return `${prefix} ${Date.now()} ${counter}`;
}

export async function askChatQuestion(page: Page, question: string) {
  const input = page.locator("textarea").last();
  await input.fill(question);
  await page.getByRole("button", { name: /skicka meddelande|send message/i }).click();
}

export async function expectOkUrl(page: Page, pattern: RegExp) {
  await expect(page).toHaveURL(pattern, { timeout: 15_000 });
}

/** Creates a shared space through the UI and returns its base path (`/spaces/<id>`). */
export async function createSpace(page: Page, name: string): Promise<string> {
  await page.goto("/spaces/list");
  await page
    .getByRole("button", { name: /skapa yta|create space/i })
    .first()
    .click();
  await page.getByLabel(/namn|name/i).fill(name);
  await page
    .getByRole("button", { name: /skapa yta|create space/i })
    .last()
    .click();
  await page.waitForURL(/\/spaces\/[^/]+\/overview$/, { timeout: 15_000 });
  return new URL(page.url()).pathname.replace(/\/overview$/, "");
}
