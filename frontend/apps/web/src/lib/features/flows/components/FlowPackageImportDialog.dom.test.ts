import { cleanup, render, screen, waitFor } from "@testing-library/svelte";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { Eneo, FlowPackageImportPlan, FlowPackageImportResult } from "@eneo/eneo-js";
import { m } from "$lib/paraglide/messages";

import FlowPackageImportDialog from "./FlowPackageImportDialog.svelte";

const goto = vi.fn();
vi.mock("$app/navigation", () => ({ goto: (...args: unknown[]) => goto(...args) }));
vi.mock("$app/paths", () => ({ resolve: (path: string) => path }));
vi.mock("$lib/components/toast", () => ({
  toast: { success: vi.fn(), error: vi.fn(), info: vi.fn() }
}));

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

function plan(): FlowPackageImportPlan {
  return {
    package_id: "local.genomforandeplan",
    package_version: "1.0.0",
    payload_schema: "eneo.flow_package.v1",
    kind: "flow",
    content_checksum: "sum",
    target_state: "draft",
    can_install_as_draft: true,
    can_publish_after_import: false,
    dependency_resolutions: [],
    omissions: [],
    package_summary: { name: "Genomförandeplan", description: "", step_count: 17 }
  } as unknown as FlowPackageImportPlan;
}

function eneo(importDraft: () => Promise<FlowPackageImportResult>): Eneo {
  return {
    flows: {
      packages: {
        createImportPlan: vi.fn(async () => plan()),
        importDraft: vi.fn(importDraft)
      }
    }
  } as unknown as Eneo;
}

const installed: FlowPackageImportResult = {
  flow_id: "flow-new",
  flow_name: "Genomförandeplan",
  import_id: "import-1",
  content_checksum: "sum",
  package_id: "local.genomforandeplan"
} as unknown as FlowPackageImportResult;

describe("FlowPackageImportDialog", () => {
  it("reads a package it was opened with and hands the installed draft to its caller", async () => {
    const oninstalled = vi.fn(async () => undefined);
    const file = new File(["zip"], "genomforandeplan.eneopkg", { type: "application/zip" });
    const client = eneo(async () => installed);
    render(FlowPackageImportDialog, {
      eneo: client,
      spaceId: "space-1",
      spaceRouteId: "space-1",
      open: true,
      showTrigger: false,
      initialFile: file,
      oninstalled
    });

    // No trigger of its own when the caller opens it.
    expect(screen.queryByRole("button", { name: m.flow_package_import_button() })).toBeNull();
    await waitFor(() =>
      expect(client.flows.packages.createImportPlan).toHaveBeenCalledWith(
        expect.objectContaining({ spaceId: "space-1", file })
      )
    );
    const submit = (await screen.findByRole("button", {
      name: m.flow_package_import_as_draft()
    })) as HTMLButtonElement;
    await waitFor(() => expect(submit.disabled).toBe(false));
    submit.click();

    await waitFor(() => expect(oninstalled).toHaveBeenCalledWith(installed));
    // Where to go next is the caller's decision, not the dialog's.
    expect(goto).not.toHaveBeenCalled();
  });

  it("lands on the draft's editor when no caller takes over", async () => {
    const file = new File(["zip"], "genomforandeplan.eneopkg", { type: "application/zip" });
    render(FlowPackageImportDialog, {
      eneo: eneo(async () => installed),
      spaceId: "space-1",
      spaceRouteId: "space-1",
      open: true,
      showTrigger: false,
      initialFile: file
    });
    const submit = (await screen.findByRole("button", {
      name: m.flow_package_import_as_draft()
    })) as HTMLButtonElement;
    await waitFor(() => expect(submit.disabled).toBe(false));
    submit.click();
    await waitFor(() => expect(goto).toHaveBeenCalledWith("/spaces/space-1/flows/flow-new"));
  });
});
