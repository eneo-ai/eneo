import { expect, test } from "./csp";
import { uniqueName } from "./helpers";

// The stack encrypts credentials (docker-compose.e2e*.yml), as production
// does, so an admin can add a provider. This one points at the stack's mock
// model server: its key is stored encrypted, then decrypted to validate the
// new model and to test the connection. The stack's database is thrown away
// after the run, and the name is unique, so a retry adds its own.
test("adds a provider and a model through the wizard, and tests the connection", async ({
  page
}) => {
  const name = uniqueName("E2E Leverantör");
  await page.goto("/admin/models");
  await page.getByRole("button", { name: "Lägg till leverantör" }).first().click();

  const wizard = page.getByRole("dialog", { name: "Lägg till modell" });
  await wizard.getByRole("button", { name: "Lägg till OpenAI" }).click();
  await wizard.getByLabel(/^Leverantörsnamn/).fill(name);
  await wizard.getByLabel(/^API-nyckel/).fill("sk-e2e-wizard");
  await wizard.getByLabel(/^Bekräfta API-nyckel/).fill("sk-e2e-wizard");
  await wizard.getByLabel(/^Endpoint-URL/).fill("http://e2e-mock-model:8200/v1");
  await wizard.getByRole("button", { name: "Nästa" }).click();

  // Stored: the wizard goes on to the new provider's models. The mock lists
  // none, so the model is added by its id, with the token limits it asks for.
  const modelId = wizard.getByLabel("Saknas modellen? Lägg till med id");
  await modelId.fill("e2e-wizard-model");
  await modelId.press("Enter");
  await expect(wizard.getByRole("checkbox", { name: /e2e-wizard-model/ })).toBeChecked();
  await wizard.getByRole("button", { name: "Lägg till 1 modell" }).click();
  await wizard.getByLabel(/^Max indatatokens/).fill("8192");
  await wizard.getByLabel(/^Max utdatatokens/).fill("2048");
  await wizard.getByLabel(/^Max utdatatokens/).press("Tab");
  await wizard.getByRole("button", { name: "Lägg till 1 modell" }).click();
  await expect(wizard).toBeHidden({ timeout: 30_000 });

  const card = page.getByRole("region", { name });
  await expect(card.getByRole("row", { name: /e2e-wizard-model/ })).toBeVisible();
  await card.getByRole("button", { name: `Testa anslutning till ${name}` }).click();
  await expect(card.getByText("Anslutningen fungerar")).toBeVisible({ timeout: 30_000 });
});
