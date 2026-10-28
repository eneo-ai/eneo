// @vitest-environment jsdom
import { cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { expectNoAxeViolations } from "@/test/axe";
import { renderInApp } from "@/test/render";
import { makeFlow, makeStep } from "./flow-fixtures";
import { FlowSettings } from "./flow-settings";
import type { TranscriptionResources } from "./flow-transcription-settings";

afterEach(cleanup);

const flow = makeFlow({
  metadata_json: {
    wizard: { transcription_enabled: true },
    form_schema: {
      fields: [{ name: "diarienummer", label: "Diarienummer", type: "text", required: true }]
    }
  }
});

const noTranscription: TranscriptionResources = { models: [], services: [] };

const resources: TranscriptionResources = {
  models: [
    { id: "tm-1", name: "whisper-large", nickname: "Tal till text" },
    { id: "tm-2", name: "whisper-small", nickname: null }
  ],
  services: [
    {
      id: "svc-1",
      name: "Ordtjänst",
      available: true,
      meets_security_classification: true,
      is_default: true
    },
    {
      id: "svc-2",
      name: "Gammal tjänst",
      available: true,
      meets_security_classification: false,
      is_default: false
    }
  ]
};

const audioFlow = makeFlow({
  steps: [
    makeStep(1, { input_type: "audio", output_mode: "transcribe_only" }),
    makeStep(2, { user_description: "Sammanfatta mötet" })
  ],
  metadata_json: {
    wizard: { transcription_enabled: true, transcription_speaker_service: { id: "svc-2" } }
  }
});

describe("FlowSettings", () => {
  it("shows the settings as facts", async () => {
    const { container } = renderInApp(
      <FlowSettings flow={flow} canEdit={false} transcription={noTranscription} onSave={vi.fn()} />
    );
    expect(screen.getByText("Diarienummer (Text, obligatoriskt)")).toBeTruthy();
    expect(screen.getByText("Inte tillåten")).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Ändra inställningar" })).toBeNull();
    await expectNoAxeViolations(container);
  });

  it("saves the name, the run form and the export switch as one change", async () => {
    const onSave = vi.fn(async () => true);
    const { container } = renderInApp(
      <FlowSettings flow={flow} canEdit transcription={noTranscription} onSave={onSave} />
    );
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

  it("names the run after one text field at a time, and saves which", async () => {
    const onSave = vi.fn(async () => true);
    renderInApp(
      <FlowSettings flow={flow} canEdit transcription={noTranscription} onSave={onSave} />
    );
    fireEvent.click(screen.getByRole("button", { name: "Ändra inställningar" }));
    const saved = screen.getByRole("group", { name: "Diarienummer" });
    fireEvent.click(within(saved).getByRole("checkbox", { name: /Namnge körningen efter fältet/ }));
    fireEvent.click(screen.getByRole("button", { name: "Lägg till fält" }));
    const added = screen.getByRole("group", { name: "Fält 2" });
    fireEvent.change(within(added).getByRole("textbox", { name: /Etikett/ }), {
      target: { value: "Möte" }
    });
    // The new field takes the role; the field that had it lets it go.
    fireEvent.click(within(added).getByRole("checkbox", { name: /Namnge körningen efter fältet/ }));
    expect(
      (
        within(saved).getByRole("checkbox", {
          name: /Namnge körningen efter fältet/
        }) as HTMLInputElement
      ).checked
    ).toBe(false);
    fireEvent.click(screen.getByRole("button", { name: "Spara inställningar" }));

    await waitFor(() => expect(onSave).toHaveBeenCalledTimes(1));
    expect(onSave).toHaveBeenCalledWith(
      expect.objectContaining({
        metadata_json: expect.objectContaining({
          form_schema: {
            fields: [
              {
                name: "diarienummer",
                label: "Diarienummer",
                type: "text",
                required: true,
                order: 1
              },
              {
                name: "möte",
                label: "Möte",
                type: "text",
                required: false,
                order: 2,
                role: "run_label"
              }
            ]
          }
        })
      })
    );
  });

  it("sends a renamed field's saved name, so the steps' reads follow it", async () => {
    const onSave = vi.fn(async () => true);
    renderInApp(
      <FlowSettings flow={flow} canEdit transcription={noTranscription} onSave={onSave} />
    );
    fireEvent.click(screen.getByRole("button", { name: "Ändra inställningar" }));
    const field = screen.getByRole("group", { name: "Diarienummer" });
    fireEvent.change(within(field).getByRole("textbox", { name: /Tekniskt namn/ }), {
      target: { value: "arendenummer" }
    });
    fireEvent.click(screen.getByRole("button", { name: "Spara inställningar" }));

    await waitFor(() => expect(onSave).toHaveBeenCalledTimes(1));
    expect(onSave).toHaveBeenCalledWith(
      expect.objectContaining({ form_field_renames: { diarienummer: "arendenummer" } })
    );
  });

  it("explains a name a step could not read, at the field, without saving", async () => {
    const onSave = vi.fn(async () => true);
    renderInApp(
      <FlowSettings flow={flow} canEdit transcription={noTranscription} onSave={onSave} />
    );
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

  it("shows how an audio flow transcribes, with a lost service and its reason", async () => {
    const { container } = renderInApp(
      <FlowSettings flow={audioFlow} canEdit={false} transcription={resources} onSave={vi.fn()} />
    );
    expect(screen.getByText("Välj en modell. Flödet kan inte publiceras utan.")).toBeTruthy();
    expect(
      screen.getByText(
        "Gammal tjänst uppfyller inte ytans säkerhetsklass. Välj en annan tjänst eller Ingen."
      )
    ).toBeTruthy();
    await expectNoAxeViolations(container);
  });

  it("saves the transcription model, language and service with the other settings", async () => {
    const onSave = vi.fn(async () => true);
    const { container } = renderInApp(
      <FlowSettings flow={audioFlow} canEdit transcription={resources} onSave={onSave} />
    );
    fireEvent.click(screen.getByRole("button", { name: "Ändra inställningar" }));
    expect(
      screen.getByText("Flödet har ett steg som tar emot ljud, så ljudet blir alltid text först.")
    ).toBeTruthy();
    await expectNoAxeViolations(container);

    fireEvent.click(screen.getByRole("combobox", { name: /Transkriberingsmodell/ }));
    fireEvent.click(await screen.findByRole("option", { name: "Tal till text" }));
    fireEvent.click(screen.getByRole("combobox", { name: /Språk/ }));
    fireEvent.click(await screen.findByRole("option", { name: "Känn igen språket" }));
    fireEvent.click(screen.getByRole("combobox", { name: /Ordtider och talare/ }));
    fireEvent.click(await screen.findByRole("option", { name: "Ordtjänst (förval)" }));
    fireEvent.click(screen.getByRole("button", { name: "Spara inställningar" }));

    await waitFor(() => expect(onSave).toHaveBeenCalledTimes(1));
    expect(onSave).toHaveBeenCalledWith(
      expect.objectContaining({
        metadata_json: {
          wizard: {
            transcription_enabled: true,
            transcription_speaker_service: { id: "svc-1" },
            transcription_model: { id: "tm-1" },
            transcription_language: "auto"
          }
        }
      })
    );
  }, 20_000);

  it("saves a renamed field and a transcription change as one edit", async () => {
    const onSave = vi.fn(async () => true);
    const withField = makeFlow({
      steps: audioFlow.steps,
      metadata_json: {
        wizard: { transcription_enabled: true, transcription_model: { id: "tm-1" } },
        form_schema: {
          fields: [{ name: "diarienummer", label: "Diarienummer", type: "text", required: true }]
        }
      }
    });
    renderInApp(
      <FlowSettings flow={withField} canEdit transcription={resources} onSave={onSave} />
    );
    fireEvent.click(screen.getByRole("button", { name: "Ändra inställningar" }));
    const field = screen.getByRole("group", { name: "Diarienummer" });
    fireEvent.change(within(field).getByRole("textbox", { name: /Tekniskt namn/ }), {
      target: { value: "arendenummer" }
    });
    fireEvent.click(screen.getByRole("combobox", { name: /Språk/ }));
    fireEvent.click(await screen.findByRole("option", { name: "English" }));
    fireEvent.click(screen.getByRole("button", { name: "Spara inställningar" }));

    await waitFor(() => expect(onSave).toHaveBeenCalledTimes(1));
    expect(onSave).toHaveBeenCalledWith(
      expect.objectContaining({
        form_field_renames: { diarienummer: "arendenummer" },
        metadata_json: expect.objectContaining({
          wizard: {
            transcription_enabled: true,
            transcription_model: { id: "tm-1" },
            transcription_language: "en"
          }
        })
      })
    );
  }, 20_000);
});
