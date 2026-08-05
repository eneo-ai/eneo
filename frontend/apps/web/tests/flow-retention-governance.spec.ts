import { expect, test } from "@playwright/test";

import { backendFetch, expectOk, uniqueName } from "./helpers";

test("tenant admin confirms organization and classification retention through the same gate", async ({
  page,
  request
}) => {
  await page.goto("/");
  const classificationName = uniqueName("Retention classification");
  const createClassification = await backendFetch(
    page,
    request,
    "/api/v1/security-classifications/",
    {
      method: "POST",
      data: {
        name: classificationName,
        description: "Browser retention confirmation",
        set_lowest_security: false
      }
    }
  );
  await expectOk(createClassification, "creating retention classification");

  // The retired route must land on the consolidated surface.
  await page.goto("/admin/flow-data-retention");
  await expect(page).toHaveURL(/\/admin\/flow-settings\?tab=retention/);
  await expect(page.getByRole("heading", { name: "Flödesinställningar" })).toBeVisible();
  await expect(page.getByText("Aktuell gallringsstatus")).toBeVisible();
  await expect(page.getByText("Gallras inte automatiskt").first()).toBeVisible();
  await expect(
    page.getByText("Automatisk gallring är avstängd – körningshistorik raderas aldrig automatiskt.")
  ).toBeVisible();
  await expect(
    page.getByText("Varje policyändring registreras i granskningsloggen", { exact: false })
  ).toBeVisible();

  const runHistorySwitch = page.getByRole("switch", {
    name: "Gallra körningshistorik automatiskt"
  });
  const noPurge = page.getByRole("switch", { name: "Spärra automatisk gallring" });
  const minimumRetention = page.getByRole("textbox", { name: "Kortaste bevarandetid" });
  await expect(minimumRetention).toHaveAttribute("placeholder", "Ingen nedre gräns");

  await runHistorySwitch.click();
  const runHistoryDays = page.getByRole("textbox", { name: "Körningshistorik: Gallra efter" });
  await runHistoryDays.fill("30");
  await minimumRetention.fill("90");
  await noPurge.click();
  await expect(page.getByText("3 osparade ändringar")).toBeVisible();
  await page.getByRole("button", { name: "Spara" }).click();

  const dialog = page.getByRole("dialog");
  await expect(
    dialog.getByRole("heading", { name: "Bekräfta ändring av gallringspolicy" })
  ).toBeVisible();
  await expect(dialog).toContainText("Gallringsbara poster nu");
  await expect(dialog).toContainText("Gallringsbara poster efter ändringen");
  await expect(dialog).toContainText("Nytillkomna gallringsbara poster");
  await expect(dialog).toContainText("Poster som inte längre är gallringsbara");
  await expect(dialog).toContainText("Tiden räknas från: tid då körningen slutfördes");
  await expect(dialog).toContainText("Tiden räknas från: uppladdningstid");
  await expect(dialog).toContainText("Inbyggda skydd");
  await expect(dialog).toContainText("Radering skjuts upp");
  await dialog.getByRole("checkbox").check();
  await dialog.getByRole("button", { name: "Bekräfta policyändring" }).click();
  await expect(dialog).not.toBeVisible();
  await expect(runHistoryDays).toHaveValue("30");
  await expect(minimumRetention).toHaveValue("90");
  await expect(noPurge).toHaveAttribute("data-state", "checked");

  // Lengthening the window is non-destructive: no confirmation gate.
  await runHistoryDays.fill("60");
  await page.getByRole("button", { name: "Spara" }).click();
  await expect(runHistoryDays).toHaveValue("60");
  await expect(dialog).not.toBeVisible();

  await page.goto("/admin/security-classifications");
  const classificationRow = page
    .getByRole("row")
    .filter({ hasText: classificationName })
    .filter({ has: page.getByRole("spinbutton") });
  await classificationRow
    .getByRole("spinbutton", { name: `Kvarhållningsdagar för ${classificationName}` })
    .fill("20");
  await classificationRow
    .getByRole("spinbutton", {
      name: `Minsta kvarhållning i dagar för ${classificationName}`
    })
    .fill("120");
  await classificationRow.getByRole("checkbox", { name: "Spärra automatisk gallring" }).check();
  await classificationRow.getByRole("button", { name: "Spara" }).click();
  await expect(
    dialog.getByRole("heading", { name: "Bekräfta ändring av gallringspolicy" })
  ).toBeVisible();
  await dialog.getByRole("checkbox").check();
  await dialog.getByRole("button", { name: "Bekräfta policyändring" }).click();
  await expect(dialog).not.toBeVisible();
  await expect(classificationRow).toContainText("Gallra efter: 20 dagar");
  await expect(classificationRow).toContainText("Minimum: 120 dagar");
  await expect(classificationRow).toContainText("Gallringsspärr: på");

  await classificationRow
    .getByRole("spinbutton", { name: `Kvarhållningsdagar för ${classificationName}` })
    .fill("");
  await classificationRow.getByRole("button", { name: "Spara" }).click();
  await expect(dialog).not.toBeVisible();
  await expect(classificationRow).not.toContainText("Gallra efter:");
  await expect(classificationRow).toContainText("Minimum: 120 dagar");
  await expect(classificationRow).toContainText("Gallringsspärr: på");

  await page.goto("/admin/flow-settings?tab=retention");
  await page.getByRole("switch", { name: "Gallra körningshistorik automatiskt" }).click();
  await expect(
    page.getByText("Automatisk gallring är avstängd – körningshistorik raderas aldrig automatiskt.")
  ).toBeVisible();
  await page.getByRole("button", { name: "Spara" }).click();
  await expect(dialog).not.toBeVisible();
  await expect(page.getByText("Gallras inte automatiskt").first()).toBeVisible();
  await expect(page.getByText("Bevarandespärrar från:", { exact: false })).toBeVisible();
  await expect(page.getByText(/Klassificeringens gallringsspärr/)).toBeVisible();

  await page.goto("/account");
  await page.getByRole("combobox", { name: "Språk" }).click();
  await page.getByRole("option", { name: "English" }).click();
  await expect(page.getByRole("combobox", { name: "Language" })).toBeVisible();

  await page.goto("/en/admin/flow-settings?tab=retention");
  await expect(page.getByRole("heading", { name: "Flow settings" })).toBeVisible();
  await expect(page.getByText("Current retention status")).toBeVisible();
  await expect(page.getByText("Not deleted automatically").first()).toBeVisible();
  await expect(page.getByRole("textbox", { name: "Minimum retention period" })).toHaveValue("90");
  await expect(page.getByRole("switch", { name: "Block automatic deletion" })).toHaveAttribute(
    "data-state",
    "checked"
  );
  await expect(page.getByText("Built-in safeguards")).toBeVisible();
  await expect(
    page.getByText(/Deletion is deferred automatically for undelivered audit records/)
  ).toBeVisible();
});
