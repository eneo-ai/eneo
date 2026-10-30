import { expect, test } from "./csp";
import { askChatQuestion, conversationLog, isChatStream, uniqueName } from "./helpers";

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
    // Keep the real authenticated request and stream metadata. Replace only the
    // model's plain-text answer, as the activity tests enrich the same stream.
    await page.route(isChatStream, async (route) => {
      const response = await route.fetch();
      let inserted = false;
      const events = (await response.text()).split(/\r?\n\r?\n/).filter(Boolean);
      const body = events.flatMap((event) => {
        if (!event.startsWith("data: ") || event === "data: [DONE]") return [event];
        const chunk: { type: string; delta?: string } = JSON.parse(event.slice(6));
        if (chunk.type !== "text-delta") return [event];
        if (inserted) return [];
        inserted = true;
        return [`data: ${JSON.stringify({ ...chunk, delta: ANSWER })}`];
      });
      expect(inserted).toBe(true);
      await route.fulfill({
        status: response.status(),
        headers: {
          "content-type": "text/event-stream",
          "x-vercel-ai-ui-message-stream": "v1"
        },
        body: body.map((event) => `${event}\n\n`).join("")
      });
    });
    await page.goto("/spaces/personal/chat");
    await askChatQuestion(page, uniqueName("Visa formler och diagram"));
    const log = conversationLog(page);
    await expect(log.locator(".katex math")).toHaveCount(2);
    await expect(log.getByText("Priser: $5 och $10.", { exact: false })).toBeVisible();
    await log.getByRole("button", { name: /fler åtgärder|more actions/i }).click();
    await page.getByRole("menuitem", { name: /kopiera som rich text|copy as rich text/i }).click();
    await expect(page.getByText("Kopierad!", { exact: true })).toBeVisible();
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
    const diagram = log.locator('[data-streamdown="mermaid"] svg[id^="mermaid-"]');
    await expect(diagram).toBeVisible();
    await expect(diagram).toHaveAccessibleName("Testflöde");
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
