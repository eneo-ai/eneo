import messages from "../src/lib/i18n/messages/sv.json";
import { expect, test } from "./csp";

test(
  "prompt name stops native typing at 200 characters and cancels its draft",
  { tag: "@vite" },
  async ({ page }) => {
    await page.goto("/admin/prompt-library");
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
  }
);
