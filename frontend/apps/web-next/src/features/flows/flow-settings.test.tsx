// @vitest-environment jsdom
import { cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { expectNoAxeViolations } from "@/test/axe";
import { renderInApp } from "@/test/render";
import { makeFlow } from "./flow-fixtures";
import { FlowSettings } from "./flow-settings";

afterEach(cleanup);

const flow = makeFlow({
  metadata_json: {
    wizard: { transcription_enabled: true },
    form_schema: {
      fields: [{ name: "diarienummer", label: "Diarienummer", type: "text", required: true }]
    }
  }
});

describe("FlowSettings", () => {
  it("shows the settings as facts", async () => {
    const { container } = renderInApp(
      <FlowSettings flow={flow} canEdit={false} onSave={vi.fn()} />
    );
    expect(screen.getByText("Diarienummer (Text, obligatoriskt)")).toBeTruthy();
    expect(screen.getByText("Inte tillåten")).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Ändra inställningar" })).toBeNull();
    await expectNoAxeViolations(container);
  });

  it("saves the name, the run form and the export switch as one change", async () => {
    const onSave = vi.fn(async () => true);
    const { container } = renderInApp(<FlowSettings flow={flow} canEdit onSave={onSave} />);
    fireEvent.click(screen.getByRole("button", { name: "Ändra inställningar" }));

    fireEvent.change(screen.getByRole("textbox", { name: /^Namn/ }), {
      target: { value: "Medborgarbrev 2" }
    });
    fireEvent.click(screen.getByRole("button", { name: "Lägg till fält" }));
    const field = screen.getByRole("group", { name: "Fält 2" });
    fireEvent.change(within(field).getByRole("textbox", { name: /Etikett/ }), {
      target: { value: "Ärendetyp" }
    });
    // The technical name follows the label until it is typed.
    expect(
      (within(field).getByRole("textbox", { name: /Tekniskt namn/ }) as HTMLInputElement).value
    ).toBe("ärendetyp");
    fireEvent.click(screen.getByRole("checkbox", { name: /Tillåt export av bevisunderlag/ }));
    await expectNoAxeViolations(container);
    fireEvent.click(screen.getByRole("button", { name: "Spara inställningar" }));

    await waitFor(() => expect(onSave).toHaveBeenCalledTimes(1));
    expect(onSave).toHaveBeenCalledWith({
      name: "Medborgarbrev 2",
      description: "Sammanfattar och besvarar brev.",
      metadata_json: {
        wizard: { transcription_enabled: true },
        form_schema: {
          fields: [
            { name: "diarienummer", label: "Diarienummer", type: "text", required: true, order: 1 },
            { name: "ärendetyp", label: "Ärendetyp", type: "text", required: false, order: 2 }
          ]
        },
        evidence_policy: { allow_export: true }
      }
    });
    expect(await screen.findByRole("button", { name: "Ändra inställningar" })).toBeTruthy();
    // The axe scan of the whole form takes a few seconds in jsdom.
  }, 20_000);

  it("explains a name a step could not read, at the field, without saving", async () => {
    const onSave = vi.fn(async () => true);
    renderInApp(<FlowSettings flow={flow} canEdit onSave={onSave} />);
    fireEvent.click(screen.getByRole("button", { name: "Ändra inställningar" }));
    const field = screen.getByRole("group", { name: "Diarienummer" });
    const name = within(field).getByRole("textbox", { name: /Tekniskt namn/ });
    fireEvent.change(name, { target: { value: "step_1" } });
    fireEvent.click(screen.getByRole("button", { name: "Spara inställningar" }));

    expect(
      await within(field).findByText(
        "Namnet ser ut som en hänvisning till ett steg, till exempel step_1. Välj ett annat."
      )
    ).toBeTruthy();
    await waitFor(() => expect(document.activeElement).toBe(name));
    expect(onSave).not.toHaveBeenCalled();
  });
});
