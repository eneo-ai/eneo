import { expect, test } from "./csp";
import sv from "../src/lib/i18n/messages/sv.json";
import { answerWithText, askChatQuestion, conversationLog, uniqueName } from "./helpers";

const ANSWER =
  String.raw`## Formler och diagram

Inline: \(E = mc^2\). Priser: $5 och $10.

\[
\sum_{i=1}^{n} i = \frac{n(n+1)}{2}
\]

` +
  "```mermaid\nflowchart LR\naccTitle: Testflöde\naccDescr: Från start till klart\nA[Start] --> B[Klart]\n```";

test(
  "renders formulas and diagrams through the production CSP and follows theme changes",
  { tag: "@vite" },
  async ({ page, context }) => {
    await context.grantPermissions(["clipboard-read", "clipboard-write"]);
    await page.addInitScript(() => localStorage.setItem("theme", "light"));
    await answerWithText(page, ANSWER);
    await page.goto("/spaces/personal/chat");
    await askChatQuestion(page, uniqueName("Visa formler och diagram"));
    const log = conversationLog(page);
    await expect(log.locator(".katex math")).toHaveCount(2);
    await expect(log.getByText("Priser: $5 och $10.", { exact: false })).toBeVisible();
    // The diagram is the answer's last render and moves its actions down: a menu opened
    // before it can follow its button out of view, where the browser stops drawing it.
    const diagram = log.locator('[data-streamdown="mermaid"] svg[id^="mermaid-"]');
    await expect(diagram).toBeVisible();
    await expect(diagram).toHaveAccessibleName("Testflöde");
    await log.getByRole("button", { name: /fler åtgärder|more actions/i }).click();
    await page
      .getByRole("menuitem", { name: /kopiera som formaterad text|copy as formatted text/i })
      .click();
    await expect(page.getByText(sv.copied, { exact: true })).toBeVisible();
    const copied = await page.evaluate(async () => {
      const [item] = await navigator.clipboard.read();
      if (!item) throw new Error("The answer was not copied");
      return {
        html: await (await item.getType("text/html")).text(),
        text: await (await item.getType("text/plain")).text()
      };
    });
    expect(copied.html).toContain("<math");
    expect(copied.text).toContain("Priser: $5 och $10.");
    const node = diagram.locator(".node rect").first();
    const lightFill = await node.evaluate((element) => getComputedStyle(element).fill);
    await expect(diagram.locator("style")).toHaveCount(1);
    await expect(diagram.locator("style")).toHaveAttribute("nonce");

    await page
      .getByRole("button", { name: /konto och inställningar|account and settings/i })
      .click();
    await page.getByRole("menuitem", { name: /^(Tema|Theme)/ }).click();
    await page.getByRole("menuitemradio", { name: /^(Mörkt|Dark)$/ }).click();
    await expect(page.locator("html")).toHaveClass(/dark/);
    await expect
      .poll(() => node.evaluate((element) => getComputedStyle(element).fill))
      .not.toBe(lightFill);

    const expand = log.getByRole("button", { name: /visa i helskärm|view fullscreen/i });
    await expand.click();
    const dialog = page.getByRole("dialog", { name: /diagram/i });
    await expect(dialog).toBeVisible();
    await expect(dialog.locator('[data-streamdown="mermaid"] svg[id^="mermaid-"]')).toBeVisible();
    await expect
      .poll(() => dialog.evaluate((element) => element.contains(document.activeElement)))
      .toBe(true);
    await page.keyboard.press("Escape");
    await expect(dialog).not.toBeVisible();
    await expect(expand).toBeFocused();

    await page.setViewportSize({ width: 320, height: 800 });
    await expect
      .poll(() => page.evaluate(() => document.documentElement.scrollWidth))
      .toBeLessThanOrEqual(320);
  }
);

const ANSWER_MENU_LAYOUTS = [
  {
    name: "a phone (390 × 844, touch)",
    use: { viewport: { width: 390, height: 844 }, hasTouch: true, isMobile: true },
    touch: true
  },
  { name: "a desktop (1280 × 800)", use: { viewport: { width: 1280, height: 800 } }, touch: false }
];

for (const layout of ANSWER_MENU_LAYOUTS) {
  test.describe(`the answer's more menu on ${layout.name}`, () => {
    test.use(layout.use);

    test(
      "shows each item's whole label on one line, inside the screen, and walks by keyboard",
      { tag: "@vite" },
      async ({ page }) => {
        await answerWithText(page, "Ett kort svar.");
        await page.goto("/spaces/personal/chat");
        await askChatQuestion(page, uniqueName("Visa svarets meny"));
        const log = conversationLog(page);
        await expect(log.getByText("Ett kort svar.")).toBeVisible();

        const more = log.getByRole("button", { name: sv.chat_more_actions });
        await more.click();
        const menu = page.getByRole("menu", { name: sv.chat_more_actions });
        await expect(menu).toBeVisible();
        // Measured once the layer's entrance (a scale) has finished.
        await menu.evaluate((element) =>
          Promise.all(
            (element.closest("[popover]") ?? element)
              .getAnimations({ subtree: true })
              .map((animation) => animation.finished)
          )
        );
        const items = menu.getByRole("menuitem");
        await expect(items.first()).toHaveText(sv.copy_as_richtext);
        await expect(items.nth(1)).toHaveText(sv.copy_as_markdown);

        const measured = await menu.evaluate((element) => {
          const box = element.getBoundingClientRect();
          const rows = [...element.querySelectorAll<HTMLElement>('[role="menuitem"]')].map(
            (item) => {
              const row = item.getBoundingClientRect();
              // The label: the item's innermost span that holds its text.
              const label = [...item.querySelectorAll<HTMLElement>("span")].find(
                (span) => span.children.length === 0 && span.textContent?.trim()
              )!;
              const lines = document.createRange();
              lines.selectNodeContents(label);
              return {
                text: label.textContent,
                clipped: label.scrollWidth > label.clientWidth,
                lines: new Set([...lines.getClientRects()].map((rect) => Math.round(rect.top)))
                  .size,
                height: row.height,
                inside: row.top >= box.top - 0.5 && row.bottom <= box.bottom + 0.5
              };
            }
          );
          return {
            left: box.left,
            right: box.right,
            top: box.top,
            bottom: box.bottom,
            width: document.documentElement.clientWidth,
            height: window.innerHeight,
            rows
          };
        });
        expect(measured.left).toBeGreaterThanOrEqual(0);
        expect(measured.right).toBeLessThanOrEqual(measured.width);
        expect(measured.top).toBeGreaterThanOrEqual(0);
        expect(measured.bottom).toBeLessThanOrEqual(measured.height);
        // A menu squeezed under its button cut "Kopiera som formaterad text" to "K…".
        expect(measured.rows.length).toBeGreaterThanOrEqual(2);
        for (const row of measured.rows) {
          expect(row, row.text ?? "").toMatchObject({ clipped: false, lines: 1, inside: true });
          if (layout.touch) expect(row.height, row.text ?? "").toBeGreaterThanOrEqual(44);
        }

        // Opened by pointer, the menu holds focus; ArrowDown walks into it and
        // Escape closes it back onto its button.
        await page.keyboard.press("ArrowDown");
        await expect(items.first()).toBeFocused();
        await page.keyboard.press("ArrowDown");
        await expect(items.nth(1)).toBeFocused();
        await page.keyboard.press("Escape");
        await expect(menu).toBeHidden();
        await expect(more).toBeFocused();
      }
    );
  });
}
