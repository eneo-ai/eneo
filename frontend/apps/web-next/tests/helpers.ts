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
  await page.getByRole("button", { name: "Submit" }).click();
}

export async function expectOkUrl(page: Page, pattern: RegExp) {
  await expect(page).toHaveURL(pattern, { timeout: 15_000 });
}
