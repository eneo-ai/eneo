// @vitest-environment jsdom
import { cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { renderInApp } from "@/test/render";
import { makeFlow, makeStep } from "./flow-fixtures";

const api = vi.hoisted(() => ({ POST: vi.fn() }));
const saved = vi.hoisted(() => ({ saveBlob: vi.fn() }));

vi.mock("@/lib/api/browser", () => ({ browserApi: api }));
vi.mock("@/features/files/signed-file-url", () => saved);

import { FlowPackageExportDialog } from "./flow-package-export-dialog";

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe("FlowPackageExportDialog layout", () => {
  it("groups the fields and says what the package holds", () => {
    renderInApp(<FlowPackageExportDialog flow={makeFlow()} open onOpenChange={vi.fn()} />);

    const identity = screen.getByRole("group", { name: "Identitet" });
    expect(within(identity).getByRole("textbox", { name: /Paket-ID/ })).toBeTruthy();
    expect(within(identity).getByRole("textbox", { name: /Version/ })).toBeTruthy();
    const presentation = screen.getByRole("group", { name: "Presentation" });
    expect(within(presentation).getByRole("textbox", { name: /Namn/ })).toBeTruthy();
    expect(within(presentation).getByRole("textbox", { name: /Beskrivning/ })).toBeTruthy();

    const contents = screen.getByRole("list", { name: /Vad som ingår i paketet/ });
    expect(within(contents).getAllByRole("listitem")).toHaveLength(2);
    expect(screen.getByText("Innehåller 2 steg.")).toBeTruthy();
    // No Word templates in this flow, so there is nothing to choose.
    expect(screen.queryByRole("checkbox", { name: "Inkludera Word-mallar" })).toBeNull();
  });

  it("leaves the Word templates out when the person says so", async () => {
    api.POST.mockResolvedValue({
      data: new Blob(["zip"]),
      response: new Response(null, { status: 200 })
    });
    renderInApp(
      <FlowPackageExportDialog
        flow={makeFlow({ steps: [makeStep(1, { output_mode: "template_fill" })] })}
        open
        onOpenChange={vi.fn()}
      />
    );
    fireEvent.click(screen.getByRole("checkbox", { name: "Inkludera Word-mallar" }));
    fireEvent.click(screen.getByRole("button", { name: "Exportera" }));

    await waitFor(() => expect(saved.saveBlob).toHaveBeenCalled());
    expect(api.POST.mock.calls[0]?.[1].body).toMatchObject({ include_templates: false });
  });
});
