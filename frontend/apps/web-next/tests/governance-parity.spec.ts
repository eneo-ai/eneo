import messages from "../src/lib/i18n/messages/sv.json";
import { expect, test } from "./csp";
import { apiPost, uniqueName } from "./helpers";

test("prompt name stops native typing at 200 characters and cancels its draft", async ({
  page
}) => {
  // An empty library offers its first prompt from the empty state instead; one stored
  // prompt keeps this test from depending on another spec having made one.
  await page.goto("/admin/prompt-library");
  await apiPost(page, "/admin/prompt-library/", {
    name: uniqueName("Governance draft"),
    description: "Native typing limit",
    text: "Answer with the organisation's instructions."
  });
  await page.reload();
  const create = page.getByRole("button", {
    name: messages.governance_prompt_create,
    exact: true
  });
  await create.click();
  const dialog = page.getByRole("dialog", {
    name: messages.governance_prompt_new_heading,
    exact: true
  });
  const name = dialog.getByRole("textbox", { name: /^Namn/ });
  await expect(name).toHaveAttribute("maxlength", "200");
  await name.pressSequentially("x".repeat(205));
  await expect(name).toHaveValue("x".repeat(200));
  await name.press("Backspace");
  await name.pressSequentially("y");
  await expect(name).toHaveValue("x".repeat(199) + "y");
  await dialog.getByRole("button", { name: messages.cancel, exact: true }).click();
  await expect(dialog).toBeHidden();
  await create.click();
  await expect(name).toHaveValue("");
  await dialog.getByRole("button", { name: messages.cancel, exact: true }).click();
});
