import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "./csp";
import { sessionResponseHeaders } from "./helpers";
import type { ActionConfig, AuditLog, CategoryConfig } from "../src/features/admin/audit/audit";

test("combines actor, action, text and dates through the real audit API and restores an expired access gate", async ({
  page,
  context
}) => {
  await page.goto("/admin/audit-logs");
  const reason = page.getByRole("combobox", { name: "Åtkomstskäl" });
  await expect(reason).toBeVisible();
  await reason.click();
  await page.getByRole("option", { name: "Säkerhetsutredning" }).click();
  const justification = page.getByLabel("Detaljerad motivering");
  await justification.fill("Verifierar auditloggens filter i isolerad testmiljö.");
  const initial = page.waitForResponse(
    (response) =>
      new URL(response.url()).pathname === "/api/v1/audit/logs" && response.status() === 200
  );
  await justification.press("Control+Enter");
  const payload = (await (await initial).json()) as { logs: AuditLog[] };
  const log = payload.logs.find((item) => {
    const actor = item.metadata.actor;
    return (
      item.actor_id &&
      actor &&
      typeof actor === "object" &&
      "email" in actor &&
      typeof actor.email === "string"
    );
  });
  expect(log, "an event with enriched synthetic actor data").toBeTruthy();
  const actor = log!.metadata.actor as { name: string; email: string };
  const text = log!.description.slice(0, 30).trim();
  const params = new URLSearchParams({
    actions: log!.action,
    search: text,
    from_date: "2020-01-01",
    to_date: "2099-01-01"
  });
  await page.goto(`/admin/audit-logs?${params}`);
  const table = page.getByRole("table", { name: "Granskningsloggar" });
  await expect(table).toBeVisible();
  await page.getByRole("button", { name: "Filter (2)" }).click();
  const filters = page.getByRole("dialog", { name: "Filter" });
  await filters.getByRole("combobox", { name: "Användare" }).fill(actor.email);
  const filtered = page.waitForResponse((response) => {
    const url = new URL(response.url());
    return (
      url.pathname === "/api/v1/audit/logs" &&
      url.searchParams.get("actor_id") === log!.actor_id &&
      response.status() === 200
    );
  });
  await page.getByRole("option", { name: actor.email, exact: true }).click();
  const response = await filtered;
  const query = new URL(response.url()).searchParams;
  expect(query.get("actions")).toBe(log!.action);
  expect(query.get("search")).toBe(text);
  expect(query.get("from_date")).toBe("2020-01-01");
  expect(query.get("to_date")).toBe("2099-01-01");
  const result = (await response.json()) as { logs: AuditLog[]; total_count: number };
  expect(result.total_count).toBeGreaterThan(0);
  expect(
    result.logs.every((item) => item.actor_id === log!.actor_id && item.action === log!.action)
  ).toBe(true);
  await filters.getByRole("button", { name: "Klar" }).click();
  await expect(table.getByText(actor.name, { exact: true }).first()).toBeVisible();
  await expect(table.getByText(actor.email, { exact: true }).first()).toBeVisible();
  await expect(page.getByRole("textbox", { name: "Sök", exact: true })).toHaveValue(text);
  await expect(page.getByRole("textbox", { name: "Sök", exact: true })).toBeEnabled();

  const retention = page.getByRole("region", { name: "Gallringspolicy" });
  await expect(retention.getByText(/Loggar äldre än/)).toBeVisible();
  await retention.getByRole("button", { name: "Ändra" }).click();
  await retention.getByRole("button", { name: "1 år", exact: true }).click();
  await expect(retention.getByRole("textbox", { name: "Gallringsperiod" })).toHaveValue("365");
  await retention.getByRole("textbox", { name: "Gallringsperiod" }).fill("1");
  await expect(retention.getByText("Varning: Kortare gallringsperiod")).toBeVisible();
  await retention.getByRole("button", { name: "Avbryt" }).click();

  await context.clearCookies({ name: "audit_session_id" });
  await page.reload();
  await expect(page.getByRole("button", { name: "Få åtkomst till loggar" })).toBeVisible();
  await expect(table).toBeHidden();
});

test("keeps configuration in URL history, stages and resets changes, and protects leaving a draft", async ({
  page
}) => {
  let writes = 0;
  page.on("request", (request) => {
    if (
      request.method() === "PATCH" &&
      new URL(request.url()).pathname.startsWith("/api/v1/audit/config")
    )
      writes++;
  });
  await page.goto("/admin/audit-logs?tab=config");
  const config = page.getByRole("tab", { name: "Kategorier", exact: true });
  await expect(config).toHaveAttribute("aria-selected", "true");
  await page.reload();
  await expect(config).toHaveAttribute("aria-selected", "true");
  await page.getByRole("button", { name: "Expandera alla" }).click();
  const checkbox = page.getByRole("checkbox", { name: "Användare skapad", exact: true });
  await expect(checkbox).toBeVisible();
  const initial = await checkbox.isChecked();
  await checkbox.setChecked(!initial);
  await expect(page.getByText("Du har osparade ändringar")).toBeVisible();
  expect(writes).toBe(0);
  await page.getByRole("tab", { name: "Granskningsloggar", exact: true }).click();
  const confirmation = page.getByRole("alertdialog", { name: "Lämna sidan?" });
  await expect(confirmation).toBeVisible();
  await confirmation.getByRole("button", { name: "Avbryt", exact: true }).click();
  await expect(config).toHaveAttribute("aria-selected", "true");
  await expect(checkbox).toBeChecked({ checked: !initial });
  await page.getByRole("button", { name: "Återställ", exact: true }).click();
  await expect(checkbox).toBeChecked({ checked: initial });
  expect(writes).toBe(0);
  await page.getByRole("tab", { name: "Granskningsloggar", exact: true }).click();
  await expect(page).not.toHaveURL(/tab=config/);
  await page.goBack();
  await expect(config).toHaveAttribute("aria-selected", "true");
  await page.goForward();
  await expect(page.getByRole("tab", { name: "Granskningsloggar", exact: true })).toHaveAttribute(
    "aria-selected",
    "true"
  );
});

// The built route and CSP are real; only these configuration endpoints are fixtures.
test("preserves remaining edits after a partial save and resets to the effective server state", async ({
  page
}) => {
  let categories: CategoryConfig[] = [
    {
      category: "admin_actions",
      enabled: true,
      action_count: 2,
      example_actions: ["user_created", "user_deleted"]
    }
  ];
  let actions: ActionConfig[] = [
    { action: "user_created", category: "admin_actions", enabled: true },
    { action: "user_deleted", category: "admin_actions", enabled: true }
  ];
  const writes: string[] = [];
  await page.route(/\/api\/v1\/audit\/config(?:\/actions)?(?:\?|$)/, async (route) => {
    const request = route.request();
    const isActions = new URL(request.url()).pathname.endsWith("/actions");
    if (request.method() === "PATCH") {
      writes.push(isActions ? "actions" : "categories");
      if (isActions) {
        await route.fulfill({
          headers: sessionResponseHeaders(route),
          status: 503,
          json: { message: "Synthetic save failure", eneo_error_code: 9024 }
        });
        return;
      }
      categories = categories.map((item) => ({ ...item, enabled: false }));
      actions = actions.map((item) =>
        item.action === "user_created" ? { ...item, enabled: false } : item
      );
    }
    await route.fulfill({
      headers: sessionResponseHeaders(route),
      json: isActions ? { actions } : { categories }
    });
  });
  await page.goto("/admin/audit-logs?tab=config");
  await page.getByRole("checkbox", { name: "Administratörsåtgärder", exact: true }).uncheck();
  await page.getByRole("button", { name: "Spara ändringar", exact: true }).click();
  await expect(page.getByText("Konfigurationen sparades delvis", { exact: true })).toBeVisible();
  expect(writes).toEqual(["categories", "actions"]);
  await page.getByRole("button", { name: "Expandera alla" }).click();
  await expect(
    page.getByRole("checkbox", { name: "Användare borttagen", exact: true })
  ).not.toBeChecked();
  await expect(page.getByText("Du har osparade ändringar")).toBeVisible();
  await page.getByRole("button", { name: "Återställ", exact: true }).click();
  await expect(
    page.getByRole("checkbox", { name: "Administratörsåtgärder", exact: true })
  ).not.toBeChecked();
  await expect(
    page.getByRole("checkbox", { name: "Användare skapad", exact: true })
  ).not.toBeChecked();
  await expect(
    page.getByRole("checkbox", { name: "Användare borttagen", exact: true })
  ).toBeChecked();
  await page.setViewportSize({ width: 320, height: 800 });
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(320);
  await page.emulateMedia({ reducedMotion: "reduce" });
  const { violations } = await new AxeBuilder({
    page: page as unknown as ConstructorParameters<typeof AxeBuilder>[0]["page"]
  })
    .include("#main-content")
    .withTags(["wcag2a", "wcag2aa", "wcag21aa", "wcag22aa"])
    .analyze();
  expect(violations).toEqual([]);
  await page.emulateMedia({ forcedColors: "active" });
  await expect(
    page.getByRole("checkbox", { name: "Användare borttagen", exact: true })
  ).toBeVisible();
});
