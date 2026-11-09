// @vitest-environment jsdom
import { cleanup, fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { renderInApp } from "@/test/render";
import { setViewport } from "@/test/setup-dom";
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

/** Whether `first` comes before `second` in the document. */
const before = (first: Element, second: Element) =>
  Boolean(first.compareDocumentPosition(second) & Node.DOCUMENT_POSITION_FOLLOWING);

describe("FlowPackageExportDialog layout", () => {
  it("leads with the name, keeps the ID under Avancerat and says what the package holds", () => {
    renderInApp(<FlowPackageExportDialog flow={makeFlow()} open onOpenChange={vi.fn()} />);

    const name = screen.getByRole("textbox", { name: /Namn/ });
    const description = screen.getByRole("textbox", { name: /Beskrivning/ });
    const advanced = screen.getByRole("button", { name: "Avancerat" });
    expect(advanced.getAttribute("aria-expanded")).toBe("false");
    expect(before(name, description) && before(description, advanced)).toBe(true);
    fireEvent.click(advanced);
    expect(advanced.getAttribute("aria-expanded")).toBe("true");
    expect(before(advanced, screen.getByRole("textbox", { name: /Paket-ID/ }))).toBe(true);
    expect(before(advanced, screen.getByRole("textbox", { name: /Version/ }))).toBe(true);

    expect(screen.getByText("Vad som ingår i paketet")).toBeTruthy();
    expect(screen.getByText("Innehåller 2 steg.")).toBeTruthy();
    expect(screen.getByText(/Körhistorik och inloggningsuppgifter följer inte med/)).toBeTruthy();
    // No Word-template clause when there is no Word template to choose.
    expect(screen.queryByText(/Word-mallar/)).toBeNull();
    expect(
      screen.getByText("Det här namnet får flödet när någon importerar paketet.")
    ).toBeTruthy();
    // No Word templates in this flow, so there is nothing to choose.
    expect(screen.queryByRole("checkbox", { name: "Inkludera Word-mallar" })).toBeNull();
  });

  it("opens Avancerat and goes to the version when it is missing", () => {
    renderInApp(<FlowPackageExportDialog flow={makeFlow()} open onOpenChange={vi.fn()} />);
    const advanced = screen.getByRole("button", { name: "Avancerat" });
    fireEvent.click(advanced);
    const version = screen.getByRole("textbox", { name: /Version/ });
    fireEvent.change(version, { target: { value: "" } });
    fireEvent.click(advanced);

    fireEvent.click(screen.getByRole("button", { name: "Exportera" }));

    expect(advanced.getAttribute("aria-expanded")).toBe("true");
    expect(document.activeElement).toBe(version);
    expect(screen.getByText("Ange en version, till exempel 1.0.0.")).toBeTruthy();
    expect(api.POST).not.toHaveBeenCalled();
  });

  it("takes the whole screen on a phone, where a dialog's header would leave too little", () => {
    setViewport("phone");
    renderInApp(<FlowPackageExportDialog flow={makeFlow()} open onOpenChange={vi.fn()} />);
    expect(screen.getByRole("dialog").getAttribute("data-variant")).toBe("fullscreen");
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
