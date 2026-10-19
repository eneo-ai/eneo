import { expect, test, type Locator, type Page } from "@playwright/test";
import { MOCK_REPLY, uniqueName } from "./helpers";

type CreatedFlow = {
  id: string;
  name: string;
};

const RUN_FLOW_LABEL = /^(Run flow|Kör flöde)$/;
const RUN_INPUT_LABEL = /^(Material|Underlag)$/;
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
const ADD_STEP_SEARCH_LABEL = /^(Search step types|Sök stegtyp)/; // flow_add_step_search
// A step type's radio is named by its title followed by its description.
const DOCUMENT_TEMPLATE_LABEL = /^(Create document|Skapa dokument)\s/; // flow_template_document_name
const DOCUMENT_FORMAT_LABEL = /^Format$/; // flow_add_step_format
const PDF_FORMAT_LABEL = /^PDF$/; // flow_add_step_format_pdf
// A closed chapter's trigger is named by its title followed by its summary.
const STAGE_CONTROL_LABEL = /^(Review and security|Granskning och säkerhet)(\s|$)/; // flow_chapter_control
const OUTPUT_CHAPTER_LABEL = /^(Result|Resultat)(\s|$)/; // flow_chapter_output
const OUTPUT_MODE_LABEL = /^(Processing and delivery|Bearbetning och leverans)$/;
const REVIEW_POLICY_LABEL = /^(Review after the step|Granskning efter steget)$/;
const REVIEW_VIEW_LABEL = /^(Review and approve result|Granska och godkänn resultatet)$/;
const PUBLISH_LABEL = /^(Publish|Publicera)$/;
const INSTRUCTIONS_LABEL = /^(Instruction for the AI|Instruktion till AI:n)$/;
const STEP_NAME_LABEL = /^(Step name|Stegnamn)\b/;
// The checkpoint panel is headed by the reviewed step's name.
const REVIEWED_STEP_NAME = "Prepare deterministic content";
const APPROVE_AND_CONTINUE_LABEL = /^(Approve and continue|Godkänn och fortsätt)$/; // flow_transcript_editor_approve_continue
const CANCEL_BUTTON_LABEL = /^(Cancel run|Avbryt körningen)$/;
const CANCEL_DIALOG_LABEL = /^(Cancel the run\?|Avbryt körningen\?)$/;
const CANCEL_ACTION_LABEL = /^(Cancel run|Avbryt körningen)$/;
// A status cell's text starts after its icon.
const COMPLETED_STATUS_LABEL = /^\s*(Completed|Slutförd)$/; // flow_run_status_completed
const CANCELLED_STATUS_LABEL = /^\s*(Cancelled|Avbruten)$/; // flow_run_status_cancelled
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
  await page.getByRole("textbox", { name: STEP_NAME_LABEL }).fill(REVIEWED_STEP_NAME);
  await page.getByRole("textbox", { name: STEP_NAME_LABEL }).press("Tab");
  await expect(page.getByRole("listitem").filter({ hasText: REVIEWED_STEP_NAME })).toBeVisible();

  await page.getByRole("button", { name: STAGE_CONTROL_LABEL }).click();
  // A select trigger is a button that opens a listbox.
  await page.getByRole("button", { name: REVIEW_POLICY_LABEL }).click();
  await page.getByRole("option", { name: REVIEW_VIEW_LABEL }).click();

  await page.getByRole("button", { name: ADD_STEP_LABEL, exact: true }).click();
  const addDialog = page.getByRole("dialog", { name: ADD_STEP_DIALOG_LABEL });
  await addDialog.getByRole("textbox", { name: ADD_STEP_SEARCH_LABEL }).fill("pdf");
  await addDialog.getByRole("radio", { name: DOCUMENT_TEMPLATE_LABEL }).click();
  await addDialog
    .getByRole("group", { name: DOCUMENT_FORMAT_LABEL })
    .getByRole("radio", { name: PDF_FORMAT_LABEL })
    .click();
  await addDialog.getByRole("button", { name: ADD_STEP_LABEL, exact: true }).click();

  const secondStep = page
    .getByRole("listitem")
    .filter({ hasText: /Create PDF document|Skapa PDF-dokument/ });
  await expect(secondStep).toBeVisible();
  await page.getByRole("button", { name: OUTPUT_CHAPTER_LABEL }).click();
  await page.getByRole("button", { name: OUTPUT_MODE_LABEL }).click();
  await page
    .getByRole("option", { name: /Create document without AI|Skapa dokument utan AI/ })
    .click();

  await page.getByRole("button", { name: NEXT_STAGE_LABEL }).click();
  await expect(page.getByRole("button", { name: PUBLISH_LABEL, exact: true })).toBeEnabled();
  await page.getByRole("button", { name: PUBLISH_LABEL, exact: true }).click();
  await expect(
    // flow_published_readonly
    page.getByText(
      /^(This flow is published and can't be changed|Flödet är publicerat och kan inte ändras)\./
    )
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

  // The run names its PDF "<flow name> <YYYY-MM-DD>.pdf" by the UTC day it was
  // created; a run started across midnight may take either day.
  const dayBeforeRun = new Date().toISOString().slice(0, 10);
  const { runRow, runTable, evidenceToggle } = await startRunFromWizard(
    page,
    flow,
    uniqueName("PDF run input")
  );
  const dayAfterRun = new Date().toISOString().slice(0, 10);

  const evidencePanel = await expandedRunPanel(page, evidenceToggle);
  await expect(
    evidencePanel.getByRole("heading", { name: REVIEWED_STEP_NAME, exact: true })
  ).toBeVisible({ timeout: 60_000 });
  // Approving continues the run in the same action.
  const approveButton = evidencePanel.getByRole("button", { name: APPROVE_AND_CONTINUE_LABEL });
  await expect(approveButton).toBeEnabled();
  await approveButton.click();

  // The reviewed result is on screen already; the run's own status says it ended.
  await expect(runRow.getByRole("cell").first()).toHaveText(COMPLETED_STATUS_LABEL, {
    timeout: 60_000
  });
  const terminalPanel = await expandedRunPanel(page, evidenceToggle);
  await expect(terminalPanel).toContainText(MOCK_REPLY, { timeout: 60_000 });

  const downloadButton = runTable.getByRole("button", { name: DOWNLOAD_PDF_LABEL });
  await expect(downloadButton).toBeVisible({ timeout: 30_000 });
  const downloadPromise = page.waitForEvent("download");
  await downloadButton.click();
  const download = await downloadPromise;
  expect([dayBeforeRun, dayAfterRun].map((day) => `${flow.name} ${day}.pdf`)).toContain(
    download.suggestedFilename()
  );
  expect(await download.failure()).toBeNull();

  const cancelledRun = await startRunFromWizard(page, flow, uniqueName("cancelled run input"));
  const cancelledPanel = await expandedRunPanel(page, cancelledRun.evidenceToggle);
  await expect(
    cancelledPanel.getByRole("heading", { name: REVIEWED_STEP_NAME, exact: true })
  ).toBeVisible({ timeout: 60_000 });
  await expect(
    cancelledPanel.getByRole("button", { name: APPROVE_AND_CONTINUE_LABEL })
  ).toBeVisible();
  await cancelledRun.runRow.getByRole("button", { name: CANCEL_BUTTON_LABEL }).click();

  const cancelDialog = page.getByRole("alertdialog", { name: CANCEL_DIALOG_LABEL });
  await cancelDialog.getByRole("button", { name: CANCEL_ACTION_LABEL }).click();
  await expect(cancelledRun.runRow.getByRole("cell").first()).toHaveText(CANCELLED_STATUS_LABEL, {
    timeout: 60_000
  });
});
