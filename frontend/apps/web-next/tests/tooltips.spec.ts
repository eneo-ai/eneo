import { expect, test } from "./csp";

/*
 * Content on hover or focus (WCAG 1.4.13): a tooltip can be dismissed without moving the pointer
 * or the focus (Escape), the pointer can move onto it without it going away, and it stays until
 * the pointer or the focus leaves or it is dismissed. The app's icon buttons use the design
 * system's tooltip; this holds it to the rule on a real page, with a mouse and with the keyboard.
 */
test.use({ viewport: { width: 1280, height: 800 } });

// The top bar's search: an icon button whose tooltip names it, on every page beside the sidebar.
const TRIGGER = /^(Sök|Search)$/;

test("a tooltip is dismissible, hoverable and persistent", { tag: "@vite" }, async ({ page }) => {
  await page.goto("/spaces/personal/chat");
  await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
  const trigger = page.getByRole("banner").getByRole("button", { name: TRIGGER });
  const tooltip = page.getByRole("tooltip").filter({ hasText: /^(Sök|Search)/ });

  await trigger.hover();
  await expect(tooltip).toBeVisible();

  // Hoverable: the pointer moves from the trigger onto the tooltip, as a hand does (a few
  // milliseconds a step across the gap between them), and the tooltip stays.
  const from = (await trigger.boundingBox())!;
  const to = (await tooltip.boundingBox())!;
  const steps = 12;
  for (let step = 1; step <= steps; step++) {
    const ratio = step / steps;
    await page.mouse.move(
      from.x + from.width / 2 + (to.x + to.width / 2 - from.x - from.width / 2) * ratio,
      from.y + from.height / 2 + (to.y + to.height / 2 - from.y - from.height / 2) * ratio
    );
    await page.waitForTimeout(25);
    await expect(tooltip).toBeVisible();
  }
  await page.waitForTimeout(600);
  await expect(tooltip).toBeVisible();

  // Persistent: it does not time out while the pointer is there.
  await page.waitForTimeout(2500);
  await expect(tooltip).toBeVisible();

  // Dismissible: Escape closes it, and the focus has not moved.
  await page.keyboard.press("Escape");
  await expect(tooltip).toBeHidden();

  // The pointer leaves; the keyboard brings it back on focus, and blur takes it away.
  await page.mouse.move(2, 2);
  await trigger.focus();
  await page.keyboard.press("Tab");
  await page.keyboard.press("Shift+Tab");
  await expect(trigger).toBeFocused();
  await expect(tooltip).toBeVisible();
  // A person's beat before pressing Escape: the tooltip has finished opening.
  await page.waitForTimeout(400);
  await page.keyboard.press("Escape");
  await expect(tooltip).toBeHidden();
  await page.keyboard.press("Tab");
  await expect(tooltip).toBeHidden();
});
