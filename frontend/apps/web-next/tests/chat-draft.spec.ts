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

// Unsent work survives a reload as a draft, but a closed tab or a deployment's
// automatic reload ends it, and files are never kept: the browser asks first.
test(
  "a reload or a closed tab asks before it ends a question that was typed and not sent",
  { tag: "@vite" },
  async ({ page }) => {
    await page.goto("/spaces/personal/chat");
    const composer = page.getByRole("textbox", { name: /^Fråga / });
    await expect(composer).toBeVisible();

    // Nothing typed, nothing to ask about: the reload goes through.
    await page.reload();
    await expect(page.getByRole("textbox", { name: /^Fråga / })).toBeVisible();

    await page.getByRole("textbox", { name: /^Fråga / }).fill("Vad kostar ett bygglov?");
    const asks = page.waitForEvent("dialog");
    // A cancelled navigation has no load event for Playwright's reload to await.
    const reload = page.evaluate(() => window.location.reload());
    const dialog = await asks;
    expect(dialog.type()).toBe("beforeunload");
    await dialog.dismiss();
    await reload;
    await expect(page.getByRole("textbox", { name: /^Fråga / })).toHaveValue(
      "Vad kostar ett bygglov?"
    );
  }
);
