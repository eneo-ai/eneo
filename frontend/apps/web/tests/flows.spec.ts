import { expect, test, type Locator, type Page } from "@playwright/test";
import { MOCK_REPLY, uniqueName } from "./helpers";

type CreatedFlow = {
  id: string;
  name: string;
};

const RUN_FLOW_LABEL = /^(Run flow|Kör flöde)$/;
const RUN_INPUT_LABEL = /^(Input|Indata)$/;
const NEXT_LABEL = /^(Next|Nästa)$/;
const START_RUN_LABEL = /^(Start run|Starta körning)$/;
const NEXT_STAGE_LABEL = /^(Next|Nästa):/;
const CREATE_FLOW_LABEL = /^(Create flow|Skapa flöde)$/;
const CREATE_FLOW_DIALOG_LABEL = /^(Create a flow|Skapa ett flöde)$/;
const MANUAL_FLOW_LABEL = /^(Build manually|Bygg manuellt)/;
const FLOW_NAME_LABEL = /^(Name|Namn)$/;
const CREATE_FLOW_ACTION_LABEL = /^(Create flow|Skapa flödet)$/;
const FLOW_DESCRIPTION_LABEL = /^(Description|Beskrivning)$/;
const EMPTY_ADD_STEP_LABEL = /^(Add your first step|Lägg till första steget)$/;
const ADD_STEP_LABEL = /^(Add step|Lägg till steg)$/;
const ADD_STEP_DIALOG_LABEL = ADD_STEP_LABEL;
const ADD_STEP_SEARCH_LABEL = /^(Search templates|Sök mall)/;
const DOCUMENT_TEMPLATE_LABEL = /^(Create document|Skapa dokument)/;
const PDF_FORMAT_LABEL = /^(PDF|PDF-dokument)$/;
const STAGE_CONTROL_LABEL = /^(Review and security|Granskning och säkerhet)$/;
const OUTPUT_CHAPTER_LABEL = /^(Result|Resultat)$/;
const OUTPUT_MODE_LABEL = /^(Processing and delivery|Bearbetning och leverans)$/;
const REVIEW_POLICY_LABEL = /^(Review after this step|Granskning efter detta steg)$/;
const REVIEW_VIEW_LABEL = /^(Review and approve result|Granska och godkänn resultatet)$/;
const PUBLISH_LABEL = /^(Publish|Publicera)$/;
const INSTRUCTIONS_LABEL = /^(Instruction for the AI|Instruktion till AI:n)$/;
const STEP_NAME_LABEL = /^(Step name|Stegnamn)$/;
const REVIEW_CHECKPOINT_LABEL = /^(Review checkpoint|Granskningspunkt)$/;
const APPROVE_LABEL = /^(Approve|Godkänn)$/;
const RESUME_LABEL = /^(Resume|Fortsätt)$/;
const CANCEL_BUTTON_LABEL = /^(Cancel|Avbryt)$/;
const CANCEL_DIALOG_LABEL = /^(Cancel run|Avbryt körning)$/;
const CANCEL_ACTION_LABEL = /^(Cancel run|Avbryt körningen)$/;
const CANCELLED_STATUS_LABEL = /^(Cancelled|Avbruten)$/;
const DOWNLOAD_PDF_LABEL = /^(Download|Ladda ner) .*\.pdf$/;

async function startRunFromWizard(page: Page, flow: CreatedFlow, input: string) {
  await page.goto("/spaces/personal/flows");
  await page.getByRole("link", { name: flow.name, exact: true }).click();

  await expect(page).toHaveURL(new RegExp(`/spaces/personal/flows/${flow.id}`));
  await page.getByRole("button", { name: RUN_FLOW_LABEL }).click();

  const dialog = page.getByRole("dialog", { name: RUN_FLOW_LABEL });
  await dialog.getByRole("textbox", { name: RUN_INPUT_LABEL }).fill(input);
  await dialog.getByRole("button", { name: NEXT_LABEL }).click();
  await dialog.getByRole("button", { name: START_RUN_LABEL }).click();

  const historyPanel = page.locator("#panel-history");
  await expect(historyPanel).toBeVisible();
  const runTable = historyPanel.getByRole("table");
  const runRow = runTable.locator("tbody tr").first();
  await expect(runRow).toBeVisible();
  await expect(runRow.getByRole("cell").first()).toContainText(/Queued|Running|I kö|Körs/, {
    timeout: 60_000
  });
  const evidenceToggle = runRow.getByTestId(/^flow-run-evidence-toggle-/);
  await expect(evidenceToggle).toBeVisible();
  return { runRow, runTable, evidenceToggle };
}

async function createPublishedFlowThroughUi(
  page: Page,
  name: string,
  description: string
): Promise<CreatedFlow> {
  await page.goto("/spaces/personal/flows");
  await page.getByRole("button", { name: CREATE_FLOW_LABEL }).click();

  const createDialog = page.getByRole("dialog", { name: CREATE_FLOW_DIALOG_LABEL });
  await createDialog.getByRole("button", { name: MANUAL_FLOW_LABEL }).click();
  await createDialog.getByRole("textbox", { name: FLOW_NAME_LABEL }).fill(`${name} draft`);
  await createDialog.getByRole("button", { name: CREATE_FLOW_ACTION_LABEL }).click();

  await page.waitForURL(/\/spaces\/personal\/flows\/([^/?]+)/);
  const flowId = new URL(page.url()).pathname.split("/").pop();
  if (!flowId) throw new Error("creating a flow should navigate to its editor");

  await page.getByRole("textbox", { name: FLOW_NAME_LABEL }).fill(name);
  await page.getByRole("textbox", { name: FLOW_NAME_LABEL }).press("Tab");
  await page.getByRole("textbox", { name: FLOW_DESCRIPTION_LABEL }).fill(description);
  for (let stage = 0; stage < 3; stage += 1) {
    await page.getByRole("button", { name: NEXT_STAGE_LABEL }).click();
  }

  await page.getByRole("button", { name: EMPTY_ADD_STEP_LABEL }).click();
  await expect(page.getByRole("textbox", { name: INSTRUCTIONS_LABEL })).toBeVisible();
  await page
    .getByRole("textbox", { name: INSTRUCTIONS_LABEL })
    .fill("Return the deterministic completion unchanged.");
  await page.getByRole("textbox", { name: STEP_NAME_LABEL }).fill("Prepare deterministic content");
  await page.getByRole("textbox", { name: STEP_NAME_LABEL }).press("Tab");
  await expect(
    page.getByRole("listitem").filter({ hasText: "Prepare deterministic content" })
  ).toBeVisible();

  await page.getByRole("button", { name: STAGE_CONTROL_LABEL }).click();
  await page.getByRole("combobox", { name: REVIEW_POLICY_LABEL }).click();
  await page.getByRole("option", { name: REVIEW_VIEW_LABEL }).click();

  await page.getByRole("button", { name: ADD_STEP_LABEL, exact: true }).click();
  const addDialog = page.getByRole("dialog", { name: ADD_STEP_DIALOG_LABEL });
  await addDialog.getByRole("textbox", { name: ADD_STEP_SEARCH_LABEL }).fill("pdf");
  await addDialog.getByRole("button", { name: DOCUMENT_TEMPLATE_LABEL }).click();
  await addDialog.getByRole("button", { name: PDF_FORMAT_LABEL, exact: true }).click();
  await addDialog.getByRole("button", { name: ADD_STEP_LABEL, exact: true }).click();

  const secondStep = page
    .getByRole("listitem")
    .filter({ hasText: /Create PDF document|Skapa PDF-dokument/ });
  await expect(secondStep).toBeVisible();
  await page.getByRole("button", { name: OUTPUT_CHAPTER_LABEL }).click();
  await page.getByRole("combobox", { name: OUTPUT_MODE_LABEL }).click();
  await page
    .getByRole("option", { name: /Create document without AI|Skapa dokument utan AI/ })
    .click();

  await page.getByRole("button", { name: NEXT_STAGE_LABEL }).click();
  await expect(page.getByRole("button", { name: PUBLISH_LABEL, exact: true })).toBeEnabled();
  await page.getByRole("button", { name: PUBLISH_LABEL, exact: true }).click();
  await expect(
    page.getByText(/Published — read-only|Publicerad – kan inte redigeras/)
  ).toBeVisible();

  return { id: flowId, name };
}

async function expandedRunPanel(page: Page, evidenceToggle: Locator): Promise<Locator> {
  if ((await evidenceToggle.getAttribute("aria-expanded")) !== "true") {
    await evidenceToggle.click();
  }
  await expect(evidenceToggle).toHaveAttribute("aria-expanded", "true");

  const panelId = await evidenceToggle.getAttribute("aria-controls");
  if (!panelId) throw new Error("run evidence toggle should control a visible panel");
  const panel = page.getByRole("table").locator(`#${panelId}`);
  await expect(panel).toBeVisible();
  return panel;
}

test("a browser-authored flow can be reviewed and downloads a PDF artifact", async ({ page }) => {
  test.setTimeout(120_000);
  await page.goto("/");

  const flow = await createPublishedFlowThroughUi(
    page,
    uniqueName("E2E PDF Flow"),
    "Deterministic browser PDF artifact Flow"
  );

  const { runTable, evidenceToggle } = await startRunFromWizard(
    page,
    flow,
    uniqueName("PDF run input")
  );

  const evidencePanel = await expandedRunPanel(page, evidenceToggle);
  await expect(evidencePanel.getByRole("heading", { name: REVIEW_CHECKPOINT_LABEL })).toBeVisible({
    timeout: 60_000
  });
  await evidencePanel.getByRole("button", { name: APPROVE_LABEL }).click();
  const resumeButton = evidencePanel.getByRole("button", { name: RESUME_LABEL });
  await expect(resumeButton).toBeEnabled();
  await resumeButton.click();

  const terminalPanel = await expandedRunPanel(page, evidenceToggle);
  await expect(terminalPanel).toContainText(MOCK_REPLY, { timeout: 60_000 });

  const downloadButton = runTable.getByRole("button", { name: DOWNLOAD_PDF_LABEL });
  await expect(downloadButton).toBeVisible();
  const downloadPromise = page.waitForEvent("download");
  await downloadButton.click();
  const download = await downloadPromise;
  expect(download.suggestedFilename()).toBe("step_2_output.pdf");
  expect(await download.failure()).toBeNull();

  const cancelledRun = await startRunFromWizard(page, flow, uniqueName("cancelled run input"));
  const cancelledPanel = await expandedRunPanel(page, cancelledRun.evidenceToggle);
  await expect(cancelledPanel.getByRole("heading", { name: REVIEW_CHECKPOINT_LABEL })).toBeVisible({
    timeout: 60_000
  });
  await cancelledRun.runRow.getByRole("button", { name: CANCEL_BUTTON_LABEL }).click();

  const cancelDialog = page.getByRole("alertdialog", { name: CANCEL_DIALOG_LABEL });
  await cancelDialog.getByRole("button", { name: CANCEL_ACTION_LABEL }).click();
  await expect(cancelledRun.runRow.getByRole("cell").first()).toHaveText(CANCELLED_STATUS_LABEL, {
    timeout: 60_000
  });
});
