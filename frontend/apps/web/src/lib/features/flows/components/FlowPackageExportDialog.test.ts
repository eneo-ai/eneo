// @vitest-environment jsdom

import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/svelte";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { Eneo, Flow, FlowPackageExportResponse } from "@eneo/eneo-js";
import { m } from "$lib/paraglide/messages";

import FlowPackageExportDialog from "./FlowPackageExportDialog.svelte";

vi.mock("$lib/components/toast", () => ({
  toast: {
    success: vi.fn(),
    error: vi.fn(),
    info: vi.fn()
  }
}));

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  vi.clearAllMocks();
  vi.unstubAllGlobals();
});

describe("FlowPackageExportDialog", () => {
  it("does not duplicate backend package-id validation in the submit gate", async () => {
    render(FlowPackageExportDialog, {
      flow: flow(),
      eneo: eneo()
    });

    await fireEvent.click(screen.getByRole("button", { name: m.flow_package_export_button() }));
    await fireEvent.input(screen.getByLabelText(m.flow_package_package_id()), {
      target: { value: "Invalid Package" }
    });

    const exportButtons = screen.getAllByRole("button", {
      name: m.flow_package_export_button()
    });
    const submitButton = exportButtons[exportButtons.length - 1];

    expect((submitButton as HTMLButtonElement).disabled).toBe(false);
  });

  it("requires acknowledgement before saving a package with omitted MCP attachments", async () => {
    const exportPackage = vi.fn(async () => exportedPackageWithMcpOmissions());
    const createObjectURL = vi.fn(() => "blob:flow-package");
    vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => undefined);
    vi.stubGlobal("URL", {
      createObjectURL,
      revokeObjectURL: vi.fn()
    });
    render(FlowPackageExportDialog, {
      flow: flow(),
      eneo: eneo(exportPackage)
    });

    await fireEvent.click(screen.getByRole("button", { name: m.flow_package_export_button() }));
    const exportButtons = screen.getAllByRole("button", {
      name: m.flow_package_export_button()
    });
    await fireEvent.click(exportButtons[exportButtons.length - 1]);

    expect(await screen.findByText(m.flow_package_export_mcp_omission_title())).toBeTruthy();
    expect(exportPackage).toHaveBeenCalledTimes(1);
    expect(createObjectURL).not.toHaveBeenCalled();

    const saveButton = screen.getByRole("button", { name: m.flow_package_save_package() });
    expect((saveButton as HTMLButtonElement).disabled).toBe(true);
    await fireEvent.click(
      screen.getByRole("checkbox", {
        name: m.flow_package_export_mcp_omission_acknowledgement()
      })
    );
    await waitFor(() => expect((saveButton as HTMLButtonElement).disabled).toBe(false));
    await fireEvent.click(saveButton);

    expect(createObjectURL).toHaveBeenCalledOnce();
    expect(exportPackage).toHaveBeenCalledTimes(1);
  });
});

function flow(): Flow {
  return {
    id: "flow-1",
    name: "Demo flow",
    description: "Reusable demo flow.",
    steps: []
  } as unknown as Flow;
}

function eneo(exportPackage: () => Promise<FlowPackageExportResponse> = vi.fn()): Eneo {
  return {
    flows: {
      packages: {
        export: exportPackage
      }
    }
  } as unknown as Eneo;
}

function exportedPackageWithMcpOmissions(): FlowPackageExportResponse {
  return {
    blob: new Blob(["pkg"]),
    contentType: "application/vnd.eneo.package+zip",
    filename: "demo.eneopkg",
    headers: new Headers(),
    omissions: [{ kind: "mcp_attachment", count: 2 }]
  };
}
