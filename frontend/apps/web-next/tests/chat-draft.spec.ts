import { expect, test } from "./csp";

test.skip(!process.env.E2E_BASE_URL, "Requires the FastAPI-served Vite build");

// A question typed and left is there when the conversation is: a tap on another
// screen, a reload, or a phone that discarded the tab while another app was open.
test.use({ viewport: { width: 390, height: 844 }, hasTouch: true, isMobile: true });

test(
  "a question that was typed and left is still in the composer",
  { tag: "@vite" },
  async ({ page }) => {
    await page.goto("/spaces/personal/chat");
    const composer = page.getByRole("textbox", { name: /^Fråga / });
    await expect(composer).toBeVisible();
    await composer.fill("Hur ansöker jag om bygglov?");
    // Writing waits for typing to pause.
    await page.waitForTimeout(600);

    await page.goto("/spaces/list");
    await page.goto("/spaces/personal/chat");
    await expect(page.getByRole("textbox", { name: /^Fråga / })).toHaveValue(
      "Hur ansöker jag om bygglov?"
    );

    await page.reload();
    await expect(page.getByRole("textbox", { name: /^Fråga / })).toHaveValue(
      "Hur ansöker jag om bygglov?"
    );

    // Emptied, it is not kept.
    await page.getByRole("textbox", { name: /^Fråga / }).fill("");
    await page.waitForTimeout(600);
    await page.reload();
    await expect(page.getByRole("textbox", { name: /^Fråga / })).toHaveValue("");
  }
);
