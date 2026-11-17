import { expect, test } from "./csp";
import {
  apiPost,
  askChatQuestion,
  conversationLog,
  MOCK_REPLY,
  sessionResponseHeaders,
  uniqueName
} from "./helpers";
import type { components } from "../src/lib/api/schema";

test("uses native period statistics, question logs and the question's conversation under production CSP", async ({
  page
}, testInfo) => {
  const requested: string[] = [];
  page.on("request", (request) => requested.push(new URL(request.url()).pathname));
  await page.goto("/spaces/list");
  const space = await apiPost(page, "/spaces/", { name: uniqueName("Insikter") });
  const assistant = await apiPost(page, `/spaces/${space}/applications/assistants/`, {
    name: uniqueName("Insiktsassistent")
  });
  await apiPost(page, `/assistants/${assistant}/`, {
    insight_enabled: true,
    logging_enabled: true
  });
  const question = uniqueName("Hur hittar jag öppettiderna?");
  await page.goto(`/dashboard/${assistant}`);
  await askChatQuestion(page, question);
  await expect(conversationLog(page)).toContainText(MOCK_REPLY);

  const seriesResponse = page.waitForResponse(
    (response) =>
      new URL(response.url()).pathname === "/api/v1/analysis/metadata-statistics/aggregated/" &&
      response.ok()
  );
  await page.goto("/admin/insights");
  const aggregatedResponse = await seriesResponse;
  expect(new URL(aggregatedResponse.url()).searchParams.get("time_zone")).toBe(
    await page.evaluate(() => Intl.DateTimeFormat().resolvedOptions().timeZone)
  );
  const series: components["schemas"]["MetadataStatisticsAggregated"] =
    await aggregatedResponse.json();
  const sessionCount = series.sessions.reduce((total, point) => total + point.count, 0);
  const questionsCount = series.questions.reduce((total, point) => total + point.count, 0);
  await expect(
    page.getByText("Konversationer startade", { exact: true }).locator("..")
  ).toContainText(new Intl.NumberFormat("sv-SE").format(sessionCount));
  await expect(page.getByText("Frågor ställda", { exact: true }).locator("..")).toContainText(
    new Intl.NumberFormat("sv-SE").format(questionsCount)
  );
  await expect(page.getByRole("link", { name: "Visa tokenanvändning" })).toHaveAttribute(
    "href",
    /\/admin\/usage\?tab=tokens&from=.*&to=/
  );
  await expect(page.getByRole("button", { name: /^Period:/ })).toBeVisible();
  await page.getByRole("switch", { name: "Jämför", exact: true }).click();
  await expect(
    page.getByText(/jämfört med föregående period|Ny aktivitet utan tidigare data/).first()
  ).toBeVisible();
  await page.getByRole("radio", { name: "Ny fråga", exact: true }).click();
  await page.getByRole("radio", { name: "Efter timme", exact: true }).click();
  await expect(
    page.getByRole("table", { name: "Assistentanvändning" }).getByRole("row")
  ).toHaveCount(25);
  await page.getByRole("radio", { name: "Efter veckodag", exact: true }).click();
  await expect(
    page.getByRole("table", { name: "Assistentanvändning" }).getByRole("row")
  ).toHaveCount(8);
  expect(requested.includes("/api/v1/analysis/counts/")).toBe(false);
  await page.screenshot({ path: testInfo.outputPath("overview.png"), fullPage: true });

  const today = await page.evaluate(() => {
    const date = new Date();
    return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}-${String(date.getDate()).padStart(2, "0")}`;
  });
  // The assistant's insights: the same view as the chat page's Insikter tab,
  // with the question history on it.
  await page.goto(`/admin/insights/assistant/${assistant}?from=${today}&to=${today}`);
  await expect(page.getByRole("button", { name: "Fråga analysen", exact: true })).toBeVisible();
  const questionButton = page.getByRole("button", { name: question, exact: true });
  await expect(questionButton).toBeVisible();
  await questionButton.click();
  const dialog = page.getByRole("dialog", { name: "Frågedetaljer" });
  const raw = dialog.getByRole("region", { name: "Loggad information som JSON" });
  await expect(raw).toBeVisible();
  // Synthetic test data only; no raw log body is retained in test evidence.
  const record: components["schemas"]["MessageLogging"] = JSON.parse((await raw.textContent())!);
  expect(record.question === question).toBe(true);
  expect(typeof record.logging_details).toBe("object");
  await page.context().grantPermissions(["clipboard-read", "clipboard-write"]);
  await dialog.getByRole("button", { name: "Kopiera", exact: true }).click();
  const copiedId = await page.evaluate(
    async () => (JSON.parse(await navigator.clipboard.readText()) as { id: string }).id
  );
  expect(copiedId === record.id).toBe(true);
  await dialog.getByRole("button", { name: "Klar", exact: true }).click();
  await expect(dialog).toBeHidden();
  await expect(questionButton).toBeFocused();

  // The question's conversation opens read-only in "Utforska konversationer".
  await page
    .getByRole("button", { name: /^Session från / })
    .first()
    .click();
  const explore = page.getByRole("dialog", { name: "Utforska konversationer" });
  await expect(explore.getByText(MOCK_REPLY)).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(explore).toBeHidden();
  // The one-shot analysis is gone; the analysis is the chat behind "Fråga analysen".
  expect(requested).not.toContain(`/api/v1/analysis/assistants/${assistant}/`);
  await page.reload();
  expect(new URL(page.url()).searchParams.get("from")).toBe(today);
});

test("keeps a direct link's period in sync with browser Back and Forward", async ({ page }) => {
  await page.goto("/spaces/list");
  const space = await apiPost(page, "/spaces/", { name: uniqueName("Historik") });
  const assistant = await apiPost(page, `/spaces/${space}/applications/assistants/`, {
    name: uniqueName("Historikassistent")
  });
  await apiPost(page, `/assistants/${assistant}/`, { insight_enabled: true });
  const route = `/admin/insights/assistant/${assistant}`;
  await page.goto(`${route}?from=2026-09-01&to=2026-09-30`);
  await expect(page.getByRole("button", { name: /^Period: 1 sep\./ })).toBeVisible();
  await page.goto(`${route}?from=2026-10-01&to=2026-10-31`);
  await page.goBack();
  await expect(page.getByRole("button", { name: /^Period: 1 sep\./ })).toBeVisible();
  await page.goForward();
  await expect(page.getByRole("button", { name: /^Period: 1 okt\./ })).toBeVisible();
});

for (const colorScheme of ["light", "dark"] as const) {
  test.describe(`chart controls on a phone in ${colorScheme} mode`, () => {
    test.use({
      viewport: { width: 320, height: 800 },
      hasTouch: true,
      isMobile: true,
      colorScheme
    });
    test("contains metric/grouping controls and the empty state", async ({ page }, testInfo) => {
      // An empty endpoint fixture isolates the responsive/empty chart interaction.
      await page.route("**/api/v1/analysis/metadata-statistics/aggregated/**", (route) =>
        route.fulfill({
          status: 200,
          headers: sessionResponseHeaders(route),
          json: { assistants: [], sessions: [], questions: [] }
        })
      );
      await page.goto("/admin/insights");
      await expect(page.getByText("Ingen aktivitet", { exact: true })).toBeVisible();
      await page.getByRole("radio", { name: "Efter timme", exact: true }).click();
      await expect(page.getByRole("radio", { name: "Efter timme", exact: true })).toBeChecked();
      expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(
        320
      );
      expect(
        (await page.getByRole("radio", { name: "Efter timme", exact: true }).boundingBox())!.height
      ).toBeGreaterThanOrEqual(44);
      for (const control of await page.getByRole("radio").all()) {
        expect(
          await control.evaluate((element) => {
            const bounds = element.getBoundingClientRect();
            const figure = element.closest("figure")!.getBoundingClientRect();
            return bounds.left >= figure.left && bounds.right <= figure.right;
          })
        ).toBe(true);
      }
      await page.getByText("Ingen aktivitet", { exact: true }).scrollIntoViewIfNeeded();
      await page.screenshot({ path: testInfo.outputPath("phone-empty.png"), fullPage: true });
    });
  });
}
