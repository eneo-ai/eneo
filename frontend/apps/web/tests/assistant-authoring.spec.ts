import { expect, test } from "@playwright/test";
import { askChatQuestion, backendFetch, expectOk, MOCK_REPLY, uniqueName } from "./helpers";

test("a created assistant can be edited and used in chat", async ({ page, request }) => {
  test.setTimeout(60_000);

  const assistantName = uniqueName("E2E Assistant");
  const prompt = "You are the e2e assistant authoring test. Answer through the mock provider.";
  const question = uniqueName("e2e assistant chat");

  await page.goto("/");

  const personalSpaceResponse = await backendFetch(page, request, "/api/v1/spaces/type/personal/");
  await expectOk(personalSpaceResponse, "loading personal space");
  const personalSpace = await personalSpaceResponse.json();

  const createAssistantResponse = await backendFetch(
    page,
    request,
    `/api/v1/spaces/${personalSpace.id}/applications/assistants/`,
    {
      method: "POST",
      data: { name: assistantName }
    }
  );
  await expectOk(createAssistantResponse, "creating assistant");
  const assistant = await createAssistantResponse.json();

  await page.goto(`/spaces/personal/assistants/${assistant.id}/edit?next=default`);
  await expect(page.getByRole("link", { name: assistantName })).toBeVisible();

  await page.getByLabel("Prompt").fill(prompt);
  await page.getByRole("button", { name: /^(Save changes|Spara ändringar)$/i }).click();
  await expect(page.getByText(/All changes saved!|Alla ändringar sparade!/i)).toBeVisible();

  await page.reload();
  await expect(page.getByLabel("Prompt")).toHaveValue(prompt);

  await page.goto(`/spaces/personal/chat/?type=assistant&id=${assistant.id}&tab=chat`);
  await expect(page.getByText(assistantName).first()).toBeVisible();

  await askChatQuestion(page, question);

  await expect(page.getByText(question, { exact: true })).toBeVisible();
  await expect(page.getByText(MOCK_REPLY)).toBeVisible({ timeout: 20_000 });
});
