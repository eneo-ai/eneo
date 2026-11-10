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

  it("refuses a version that is not three numbers, at the field", () => {
    renderInApp(<FlowPackageExportDialog flow={makeFlow()} open onOpenChange={vi.fn()} />);
    fireEvent.click(screen.getByRole("button", { name: "Avancerat" }));
    const version = screen.getByRole("textbox", { name: /Version/ });
    fireEvent.change(version, { target: { value: "ett" } });

    fireEvent.click(screen.getByRole("button", { name: "Exportera" }));

    expect(document.activeElement).toBe(version);
    expect(
      screen.getByText("Skriv versionen som tre tal med punkt emellan, till exempel 1.0.0.")
    ).toBeTruthy();
    expect(api.POST).not.toHaveBeenCalled();
  });

  it("names the HTTP steps that cannot travel before export, and does not export", () => {
    renderInApp(
      <FlowPackageExportDialog
        flow={makeFlow({
          steps: [
            makeStep(1, { input_source: "http_get", user_description: "Hämta ärendet" }),
            makeStep(2),
            makeStep(3, { output_mode: "http_post", user_description: "Skicka resultatet" })
          ]
        })}
        open
        onOpenChange={vi.fn()}
      />
    );

    expect(screen.getByText("HTTP-steg följer inte med i paket")).toBeTruthy();
    expect(screen.getByText("Steg 1: Hämta ärendet")).toBeTruthy();
    expect(screen.getByText("Steg 3: Skicka resultatet")).toBeTruthy();
    expect(screen.queryByText(/Steg nummer 2/)).toBeNull();
    expect(
      screen.getByText("Ta bort stegen före export och lägg till dem igen efter importen.")
    ).toBeTruthy();
    const exportButton = screen.getByRole("button", { name: "Exportera" });
    expect(
      exportButton.hasAttribute("disabled") || exportButton.getAttribute("aria-disabled") === "true"
    ).toBe(true);
    fireEvent.submit(exportButton.closest("dialog")!.querySelector("form")!);
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
