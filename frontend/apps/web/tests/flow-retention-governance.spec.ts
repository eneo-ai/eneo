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

  await page.goto("/admin/flow-data-retention");
  await expect(page.getByRole("heading", { name: "Gallring av flödesdata" })).toBeVisible();
  await expect(page.getByText("Nuvarande gallringshölje")).toBeVisible();
  await expect(page.getByText("Körningshistorik: Automatisk radering är avstängd")).toBeVisible();
  await expect(page.getByText("Aldrig anslutna uppladdningar använder created_at")).toBeVisible();
  await expect(
    page.getByText("Varje policyaktivering registrerar administratörens identitet")
  ).toBeVisible();

  const runHistory = page.getByRole("spinbutton", { name: "Körningshistorik" });
  const uploads = page.getByRole("spinbutton", { name: "Aldrig anslutna uppladdningar" });
  await expect(runHistory).toHaveAttribute("placeholder", "Automatisk radering är avstängd");
  await expect(uploads).toHaveAttribute("placeholder", "Automatisk radering är avstängd");

  await runHistory.fill("30");
  await page.getByRole("button", { name: "Spara" }).click();

  const dialog = page.getByRole("dialog");
  await expect(
    dialog.getByRole("heading", { name: "Bekräfta destruktiv gallringsändring" })
  ).toBeVisible();
  await expect(dialog).toContainText("Livscykelhinder och vilande värden");
  await expect(dialog).toContainText("Klockfält: finished_at_or_created_at");
  await expect(dialog).toContainText("Klockfält: created_at");
  await expect(dialog).toContainText("Implementerade raderingshinder");
  await expect(dialog).toContainText("Radering skjuts upp");
  await expect(dialog).toContainText("Ej levererad granskning");
  await expect(dialog).toContainText("Olöst webhook");
  await expect(dialog).toContainText("Aktiv omkörning");
  await dialog.getByRole("checkbox").check();
  await dialog.getByRole("button", { name: "Bekräfta policyändring" }).click();
  await expect(dialog).not.toBeVisible();
  await expect(runHistory).toHaveValue("30");

  await runHistory.fill("60");
  await page.getByRole("button", { name: "Spara" }).click();
  await expect(runHistory).toHaveValue("60");
  await expect(dialog).not.toBeVisible();

  await page.goto("/admin/security-classifications");
  const classificationRow = page
    .getByRole("row")
    .filter({ hasText: classificationName })
    .filter({ has: page.getByRole("spinbutton") });
  await classificationRow.getByRole("spinbutton").fill("20");
  await classificationRow.getByRole("button", { name: "Spara" }).click();
  await expect(
    dialog.getByRole("heading", { name: "Bekräfta destruktiv gallringsändring" })
  ).toBeVisible();
  await dialog.getByRole("checkbox").check();
  await dialog.getByRole("button", { name: "Bekräfta policyändring" }).click();
  await expect(dialog).not.toBeVisible();
  await expect(classificationRow).toContainText("20 dagar");

  await page.goto("/account");
  await page.getByRole("combobox", { name: "Språk" }).click();
  await page.getByRole("option", { name: "English" }).click();
  await expect(page.getByRole("combobox", { name: "Language" })).toBeVisible();

  await page.goto("/en/admin/flow-data-retention");
  await expect(page.getByRole("heading", { name: "Flow data retention" })).toBeVisible();
  await expect(page.getByRole("spinbutton", { name: "Never-attached uploads" })).toHaveAttribute(
    "placeholder",
    "Automatic deletion is off"
  );
  await expect(page.getByText("Implemented deletion blockers")).toBeVisible();
  await expect(page.getByText(/Deletion is deferred for undelivered audit delivery/)).toBeVisible();
});
