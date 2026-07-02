// @vitest-environment jsdom

import { cleanup, fireEvent, render, screen } from "@testing-library/svelte";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { Flow, Eneo } from "@eneo/eneo-js";
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
});

function flow(): Flow {
  return {
    id: "flow-1",
    name: "Demo flow",
    description: "Reusable demo flow.",
    steps: []
  } as unknown as Flow;
}

function eneo(): Eneo {
  return {
    flows: {
      packages: {
        export: vi.fn()
      }
    }
  } as unknown as Eneo;
}
