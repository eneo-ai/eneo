import { page } from "@vitest/browser/context";
import { render } from "vitest-browser-svelte";
import { beforeEach, describe, expect, test, vi } from "vitest";
import "../../../../../app.css";

vi.mock("$lib/paraglide/messages", () => ({
  m: new Proxy<Record<string, (params?: Record<string, unknown>) => string>>(
    {},
    {
      get: (_target, key) => (params?: Record<string, unknown>) =>
        params ? `${String(key)} ${JSON.stringify(params)}` : String(key)
    }
  )
}));

const manager = vi.hoisted(() => ({
  deleteFlow: vi.fn(),
  readEvidenceExportAllowed: vi.fn()
}));
vi.mock("$lib/features/flows/FlowsManager", () => ({
  getFlowsManager: () => manager
}));

import type { FlowSparse } from "@eneo/eneo-js";
import FlowActions from "./FlowActions.svelte";

const flow = { id: "flow-1", name: "Protokoll" } as FlowSparse;
const WARNING = "flow_delete_evidence_export_off";

async function openDeleteDialog() {
  render(FlowActions, { flow });
  await page.getByRole("button", { name: "actions" }).click();
  await page.getByRole("menuitem", { name: "delete" }).click();
}

describe("FlowActions delete dialog", () => {
  beforeEach(() => {
    manager.deleteFlow.mockReset().mockResolvedValue(undefined);
    manager.readEvidenceExportAllowed.mockReset();
  });

  test("warns that the runs' evidence can never be downloaded when download is off", async () => {
    manager.readEvidenceExportAllowed.mockResolvedValue(false);

    await openDeleteDialog();

    await expect.element(page.getByText(WARNING)).toBeVisible();
    expect(manager.readEvidenceExportAllowed).toHaveBeenCalledWith("flow-1");
    await page.getByRole("button", { name: "delete" }).click();
    expect(manager.deleteFlow).toHaveBeenCalledWith("flow-1");
  });

  test("adds nothing when download is on", async () => {
    manager.readEvidenceExportAllowed.mockResolvedValue(true);

    await openDeleteDialog();

    await expect.element(page.getByRole("button", { name: "delete" })).toBeEnabled();
    await expect.element(page.getByText(WARNING)).not.toBeInTheDocument();
  });

  test("warns when the setting cannot be read, rather than staying silent", async () => {
    manager.readEvidenceExportAllowed.mockRejectedValue(new Error("offline"));

    await openDeleteDialog();

    await expect.element(page.getByText(WARNING)).toBeVisible();
    await expect.element(page.getByRole("button", { name: "delete" })).toBeEnabled();
  });

  test("does not offer delete before it knows what the warning should say", async () => {
    manager.readEvidenceExportAllowed.mockReturnValue(new Promise<boolean>(() => undefined));

    await openDeleteDialog();

    await expect.element(page.getByRole("button", { name: "delete" })).toBeDisabled();
  });
});
