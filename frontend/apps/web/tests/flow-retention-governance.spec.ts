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
  await expect(page.getByText("Vad gäller just nu")).toBeVisible();
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
  const noPurge = page.getByRole("switch", { name: "Pausa automatisk gallring" });
  const minimumRetention = page.getByRole("textbox", { name: "Kortaste bevarandetid" });
  await expect(minimumRetention).toHaveAttribute("placeholder", "Ingen nedre gräns");

  await runHistorySwitch.click();
  const runHistoryDays = page.getByRole("textbox", { name: "Körningshistorik: Gallra efter" });
  await runHistoryDays.fill("30");
  await minimumRetention.fill("90");
  await noPurge.click();
  await expect(page.getByText("3 osparade ändringar")).toBeVisible();
  await page.getByRole("button", { name: "Spara ändringar" }).click();

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
  await page.getByRole("button", { name: "Spara ändringar" }).click();
  await expect(runHistoryDays).toHaveValue("60");
  await expect(dialog).not.toBeVisible();

  await page.goto("/admin/security-classifications");
  await expect(page.getByRole("heading", { name: "Säkerhet" })).toBeVisible();
  await expect(page.getByText("Gallring av flödesdata")).not.toBeVisible();

  await page.goto("/admin/flow-settings?tab=retention");
  await page.getByRole("button", { name: `Ändra regel för ${classificationName}` }).click();
  const classificationSheet = page.getByRole("dialog", { name: classificationName });
  const deleteAfterInput = classificationSheet.getByRole("spinbutton", {
    name: `Gallra efter dagar för ${classificationName}`
  });
  const minimumInput = classificationSheet.getByRole("spinbutton", {
    name: `Minsta bevarandetid i dagar för ${classificationName}`
  });
  await deleteAfterInput.fill("20");
  await minimumInput.fill("120");
  await classificationSheet
    .getByRole("switch", { name: `Pausa automatisk gallring: ${classificationName}` })
    .click();
  await classificationSheet.getByRole("button", { name: "Granska och spara" }).click();
  await expect(
    dialog.getByRole("heading", { name: "Bekräfta ändring av gallringspolicy" })
  ).toBeVisible();
  await dialog.getByRole("checkbox").check();
  await dialog.getByRole("button", { name: "Bekräfta policyändring" }).click();
  await expect(dialog).not.toBeVisible();
  await expect(page.getByRole("cell", { name: "20 dagar" })).toBeVisible();
  await expect(page.getByRole("cell", { name: "120 dagar" })).toBeVisible();
  await expect(page.getByText("Pausad").first()).toBeVisible();
  await expect(page.getByText("1 klassificering har egna gallringsregler.")).toBeVisible();

  await page.getByRole("button", { name: `Ändra regel för ${classificationName}` }).click();
  const reopenedSheet = page.getByRole("dialog", { name: classificationName });
  const reopenedDeleteAfter = reopenedSheet.getByRole("spinbutton", {
    name: `Gallra efter dagar för ${classificationName}`
  });
  await reopenedDeleteAfter.fill("");
  await reopenedSheet.getByRole("button", { name: "Granska och spara" }).click();
  await expect(dialog).not.toBeVisible();
  await expect(page.getByRole("cell", { name: "Organisationens regel" }).first()).toBeVisible();
  await expect(page.getByRole("cell", { name: "120 dagar" })).toBeVisible();

  await page.goto("/admin/flow-settings?tab=retention");
  await page.getByRole("switch", { name: "Gallra körningshistorik automatiskt" }).click();
  await expect(
    page.getByText("Automatisk gallring är avstängd – körningshistorik raderas aldrig automatiskt.")
  ).toBeVisible();
  await page.getByRole("button", { name: "Spara ändringar" }).click();
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
  await expect(page.getByText("Current settings")).toBeVisible();
  await expect(page.getByText("Not deleted automatically").first()).toBeVisible();
  await expect(page.getByRole("textbox", { name: "Minimum retention period" })).toHaveValue("90");
  await expect(page.getByRole("switch", { name: "Pause automatic deletion" })).toHaveAttribute(
    "data-state",
    "checked"
  );
  await expect(page.getByText("Built-in safeguards")).toBeVisible();
  await expect(
    page.getByText(/Deletion is deferred automatically for undelivered audit records/)
  ).toBeVisible();
});
