// @vitest-environment jsdom
import { act, cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";
import messages from "@/lib/i18n/messages/sv.json";
import { afterEach, describe, expect, it, vi } from "vitest";
import { expectNoAxeViolations } from "@/test/axe";
import { renderInApp } from "@/test/render";
import { reportResize, setViewport } from "@/test/setup-dom";
import { makeFlow, makeStep } from "./flow-fixtures";
import { FlowSettings, SettingsSummary } from "./flow-settings";
import type { TranscriptionResources } from "./flow-transcription";

vi.mock("@/lib/navigation", () => import("@/test/navigation"));

const announce = vi.hoisted(() => vi.fn());
vi.mock("@astryxdesign/core/hooks", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@astryxdesign/core/hooks")>()),
  useAnnounce: () => announce
}));

afterEach(() => {
  cleanup();
  announce.mockClear();
});

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

/** What a row of the read view says. */
function rowValue(label: string): string | null | undefined {
  return screen.getByText(label).closest("dt")?.nextElementSibling?.textContent;
}

/** What the browser asks before a reload or a closed tab: a cancelled beforeunload means "ask". */
function asksBeforeUnload(): boolean {
  const event = new Event("beforeunload", { cancelable: true });
  window.dispatchEvent(event);
  return event.defaultPrevented;
}

describe("FlowSettings", () => {
  it("shows the settings as facts", async () => {
    const { container } = renderInApp(
      <FlowSettings flow={flow} canEdit={false} transcription={noTranscription} onSave={vi.fn()} />
    );
    expect(screen.getByText("Diarienummer (Text, obligatoriskt)")).toBeTruthy();
    expect(rowValue("Nedladdning av bevisunderlag")).toBe("Av");
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
    // The download switch is a group of its own, not one of the transcription's settings.
    fireEvent.click(
      within(screen.getByRole("region", { name: "Bevisunderlag" })).getByRole("switch", {
        name: /Nedladdning av bevisunderlag/
      })
    );
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

  it("moves a run-form field with its buttons, keeps focus on it and says where it went", async () => {
    const onSave = vi.fn(async () => true);
    const twoFields = makeFlow({
      metadata_json: {
        form_schema: {
          fields: [
            { name: "diarienummer", label: "Diarienummer", type: "text", required: true, order: 1 },
            { name: "datum", label: "Datum", type: "date", required: false, order: 2 }
          ]
        }
      }
    });
    renderInApp(
      <FlowSettings flow={twoFields} canEdit transcription={noTranscription} onSave={onSave} />
    );
    fireEvent.click(screen.getByRole("button", { name: "Ändra inställningar" }));
    const order = () =>
      screen
        .getAllByRole("group", { name: /^(Diarienummer|Datum)$/ })
        .map(
          (group) =>
            document.getElementById(group.getAttribute("aria-labelledby") ?? "")?.textContent
        );
    const button = (name: string) => screen.getByRole("button", { name }) as HTMLButtonElement;
    expect(order()).toEqual(["Diarienummer", "Datum"]);
    // The first field cannot go up, the last cannot go down.
    expect(button("Flytta upp Diarienummer").getAttribute("aria-disabled")).toBe("true");
    expect(button("Flytta ner Datum").getAttribute("aria-disabled")).toBe("true");

    fireEvent.click(screen.getByRole("button", { name: "Flytta ner Diarienummer" }));
    expect(order()).toEqual(["Datum", "Diarienummer"]);
    expect(announce).toHaveBeenCalledWith("Diarienummer flyttades till plats 2");
    // At the end its down button is off, so its up button keeps the focus.
    await waitFor(() => expect(document.activeElement).toBe(button("Flytta upp Diarienummer")));

    fireEvent.click(screen.getByRole("button", { name: "Spara inställningar" }));
    await waitFor(() => expect(onSave).toHaveBeenCalledTimes(1));
    expect(onSave).toHaveBeenCalledWith(
      expect.objectContaining({
        metadata_json: {
          form_schema: {
            fields: [
              { name: "datum", label: "Datum", type: "date", required: false, order: 1 },
              {
                name: "diarienummer",
                label: "Diarienummer",
                type: "text",
                required: true,
                order: 2
              }
            ]
          }
        }
      })
    );
    // Reordering renames nothing.
    expect(onSave).toHaveBeenCalledWith(
      expect.not.objectContaining({ form_field_renames: expect.anything() })
    );
  });

  it("says a field without a label by the number it has once moved, as its row now does", () => {
    renderInApp(
      <FlowSettings flow={makeFlow()} canEdit transcription={noTranscription} onSave={vi.fn()} />
    );
    fireEvent.click(screen.getByRole("button", { name: "Ändra inställningar" }));
    // Two new fields, nothing typed yet: their titles are their places.
    fireEvent.click(screen.getByRole("button", { name: "Lägg till fält" }));
    fireEvent.click(screen.getByRole("button", { name: "Lägg till fält" }));
    const titles = () =>
      screen
        .getAllByRole("group", { name: /^Fält \d$/ })
        .map((group) => group.getAttribute("aria-labelledby")!)
        .map((id) => document.getElementById(id)?.textContent);
    expect(titles()).toEqual(["Fält 1", "Fält 2"]);
    const moving = screen.getByRole("button", { name: "Flytta upp Fält 2" });
    const row = moving.closest<HTMLElement>('[role="group"]')!;
    fireEvent.click(moving);
    // Its row is the first now, so it is "Fält 1": the announcement says the same.
    expect(announce).toHaveBeenCalledWith("Fält 1 flyttades till plats 1");
    expect(document.getElementById(row.getAttribute("aria-labelledby")!)?.textContent).toBe(
      "Fält 1"
    );
  });

  it("folds a technical name that follows its label, and opens it when it needs a look", async () => {
    const onSave = vi.fn(async () => true);
    const typed = makeFlow({
      metadata_json: {
        form_schema: {
          fields: [
            { name: "diarienummer", label: "Diarienummer", type: "text" },
            { name: "arende_id", label: "Ärende", type: "text" }
          ]
        }
      }
    });
    renderInApp(
      <FlowSettings flow={typed} canEdit transcription={noTranscription} onSave={onSave} />
    );
    fireEvent.click(screen.getByRole("button", { name: "Ändra inställningar" }));
    const nameToggle = (group: string) =>
      within(screen.getByRole("group", { name: group })).getByRole("button", {
        name: /^Stegen läser fältet som/
      });
    // The trigger says how the steps read the field, so the name itself can stay folded.
    expect(nameToggle("Diarienummer").textContent).toContain("{{flow_input.diarienummer}}");
    expect(nameToggle("Diarienummer").getAttribute("aria-expanded")).toBe("false");
    // A name typed apart from its label is shown.
    expect(nameToggle("Ärende").getAttribute("aria-expanded")).toBe("true");
    // The run-name role stays in view either way.
    expect(
      within(screen.getByRole("group", { name: "Diarienummer" })).getByRole("checkbox", {
        name: /Namnge körningen efter fältet/
      })
    ).toBeTruthy();

    // A new field's name follows its label, folded; left empty it opens before the save
    // moves focus to it.
    fireEvent.click(screen.getByRole("button", { name: "Lägg till fält" }));
    expect(nameToggle("Fält 3").getAttribute("aria-expanded")).toBe("false");
    fireEvent.click(screen.getByRole("button", { name: "Spara inställningar" }));
    expect(nameToggle("Fält 3").getAttribute("aria-expanded")).toBe("true");
    const name = within(screen.getByRole("group", { name: "Fält 3" })).getByRole("textbox", {
      name: /Tekniskt namn/
    });
    await waitFor(() => expect(document.activeElement).toBe(name));
    expect(onSave).not.toHaveBeenCalled();
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

  it("chooses a live recording model apart from the transcription model, and says what each writes", async () => {
    const onSave = vi.fn(async () => true);
    const withLive: TranscriptionResources = {
      ...resources,
      models: [
        ...resources.models,
        {
          id: "live-1",
          name: "pianissimo-sv-live",
          nickname: "Pianissimo",
          supports_realtime: true
        }
      ]
    };
    const whisperFlow = makeFlow({
      steps: audioFlow.steps,
      metadata_json: {
        wizard: {
          transcription_enabled: true,
          transcription_model: { id: "tm-1" },
          transcription_speaker_service: null
        }
      }
    });
    const { container } = renderInApp(
      <FlowSettings flow={whisperFlow} canEdit transcription={withLive} onSave={onSave} />
    );
    expect(rowValue("Direktinspelning")).toBe("Ingen direktinspelning");
    expect(rowValue("Ljudfiler")).toBe("Tal till text");
    fireEvent.click(screen.getByRole("button", { name: "Ändra inställningar" }));

    const live = screen.getByRole("combobox", { name: /Modell för direktinspelning/ });
    expect(live.textContent).toContain("Ingen direktinspelning");
    fireEvent.click(live);
    // The transcription model's list offers the same model, so pick from this list.
    const liveList = await waitFor(() =>
      document.getElementById(live.getAttribute("aria-controls") ?? "")!
    );
    fireEvent.click(await within(liveList).findByRole("option", { name: "Pianissimo" }));
    expect(
      screen.getByText(
        "Skriver texten medan någon spelar in, och den texten blir transkriberingen."
      )
    ).toBeTruthy();
    // The routing at the top of the form follows the choice.
    expect(rowValue("Direktinspelning")).toBe("Pianissimo");
    await expectNoAxeViolations(container);
    fireEvent.click(screen.getByRole("button", { name: "Spara inställningar" }));

    await waitFor(() => expect(onSave).toHaveBeenCalledTimes(1));
    expect(onSave).toHaveBeenCalledWith(
      expect.objectContaining({
        metadata_json: {
          wizard: {
            transcription_enabled: true,
            transcription_model: { id: "tm-1" },
            transcription_speaker_service: null,
            transcription_live_model: { id: "live-1" }
          }
        }
      })
    );
  }, 20_000);

  it("keeps a live text model the space lost visible, with a warning, until it is changed", () => {
    const lostLive = makeFlow({
      steps: audioFlow.steps,
      metadata_json: {
        wizard: {
          transcription_enabled: true,
          transcription_model: { id: "tm-1" },
          transcription_speaker_service: null,
          transcription_live_model: { id: "gone" }
        }
      }
    });
    renderInApp(
      <FlowSettings flow={lostLive} canEdit={false} transcription={resources} onSave={vi.fn()} />
    );
    expect(rowValue("Direktinspelning")).toBe(
      "Den valda modellen kan inte längre användas för direktinspelning i ytan, så filerna transkriberas efteråt. Välj en annan."
    );
  });

  it("warns when a streaming model writes the files, and keeps it streaming when files move", async () => {
    const onSave = vi.fn(async () => true);
    const withLive: TranscriptionResources = {
      ...resources,
      models: [
        ...resources.models,
        {
          id: "live-1",
          name: "pianissimo-sv-live",
          nickname: "Pianissimo",
          supports_realtime: true
        }
      ]
    };
    const streamingFlow = makeFlow({
      steps: audioFlow.steps,
      metadata_json: {
        wizard: {
          transcription_enabled: true,
          transcription_model: { id: "live-1" },
          transcription_speaker_service: null
        }
      }
    });
    renderInApp(
      <FlowSettings flow={streamingFlow} canEdit transcription={withLive} onSave={onSave} />
    );
    expect(rowValue("Direktinspelning")).toBe("Pianissimo");
    expect(rowValue("Ljudfiler")).toBe("Pianissimo");
    fireEvent.click(screen.getByRole("button", { name: "Ändra inställningar" }));
    expect(
      screen.getByText(
        "Gjord för direktinspelning. Välj en modell för ljudfiler, till exempel Tal till text. Pianissimo skriver då fortfarande direktinspelningen."
      )
    ).toBeTruthy();

    const model = screen.getByRole("combobox", { name: /Transkriberingsmodell/ });
    fireEvent.click(model);
    const list = await waitFor(() =>
      document.getElementById(model.getAttribute("aria-controls") ?? "")!
    );
    fireEvent.click(await within(list).findByRole("option", { name: /Tal till text/ }));
    expect(rowValue("Direktinspelning")).toBe("Pianissimo");
    expect(rowValue("Ljudfiler")).toBe("Tal till text");
    expect(screen.queryByText(/Gjord för direktinspelning/)).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Spara inställningar" }));

    await waitFor(() => expect(onSave).toHaveBeenCalledTimes(1));
    expect(onSave).toHaveBeenCalledWith(
      expect.objectContaining({
        metadata_json: {
          wizard: expect.objectContaining({
            transcription_model: { id: "tm-1" },
            transcription_live_model: { id: "live-1" }
          })
        }
      })
    );
  }, 20_000);

  it("promises nothing about live recording when another model streams", async () => {
    const twoStreaming: TranscriptionResources = {
      ...resources,
      models: [
        ...resources.models,
        {
          id: "live-1",
          name: "pianissimo-sv-live",
          nickname: "Pianissimo",
          supports_realtime: true
        },
        { id: "live-2", name: "forte-sv-live", nickname: "Forte", supports_realtime: true }
      ]
    };
    const flowWithBoth = makeFlow({
      steps: audioFlow.steps,
      metadata_json: {
        wizard: {
          transcription_enabled: true,
          transcription_model: { id: "live-1" },
          transcription_live_model: { id: "live-2" },
          transcription_speaker_service: null
        }
      }
    });
    renderInApp(
      <FlowSettings flow={flowWithBoth} canEdit transcription={twoStreaming} onSave={vi.fn()} />
    );
    expect(rowValue("Direktinspelning")).toBe("Forte");
    fireEvent.click(screen.getByRole("button", { name: "Ändra inställningar" }));
    expect(
      screen.getByText(
        "Gjord för direktinspelning. Välj en modell för ljudfiler, till exempel Tal till text."
      )
    ).toBeTruthy();

    const model = screen.getByRole("combobox", { name: /Transkriberingsmodell/ });
    fireEvent.click(model);
    const list = await waitFor(() =>
      document.getElementById(model.getAttribute("aria-controls") ?? "")!
    );
    fireEvent.click(await within(list).findByRole("option", { name: /Tal till text/ }));
    expect(rowValue("Direktinspelning")).toBe("Forte");
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
  it("sums up the flow without what the page's header and step list already say", () => {
    renderInApp(
      <FlowSettings flow={flow} canEdit={false} transcription={noTranscription} onSave={vi.fn()} />
    );
    expect(rowValue("Formulärfält")).toContain("1");
    expect(screen.getByRole("heading", { level: 3, name: "Transkribering" })).toBeTruthy();
    expect(rowValue("Nedladdning av bevisunderlag")).toBe("Av");
    // The header names and describes the flow, and the step list follows.
    for (const repeated of ["Namn", "Beskrivning", "Steg"]) {
      expect(screen.queryByText(repeated, { selector: "dt" })).toBeNull();
    }
  });

  it("sums up a flow for a page without the space's transcription resources", () => {
    renderInApp(<SettingsSummary flow={audioFlow} />);
    expect(rowValue("Transkribering")).toBe("På");
    // No model list here: a chosen model is not called unavailable.
    expect(screen.queryByText("Transkriberingsmodell")).toBeNull();
    // Standing alone it says what the flow is for and how many steps it has, but not its name.
    expect(rowValue("Beskrivning")).toBe("Sammanfattar och besvarar brev.");
    expect(rowValue("Steg")).toBe("2");
    expect(screen.queryByText("Namn", { selector: "dt" })).toBeNull();
  });

  it("always offers transcription: off in the read view, a switch in the form", async () => {
    const onSave = vi.fn(async () => true);
    const textFlow = makeFlow();
    renderInApp(<FlowSettings flow={textFlow} canEdit transcription={resources} onSave={onSave} />);
    // Rows with nothing to say are left out: no transcription, no run form.
    expect(screen.queryByText("Transkribering")).toBeNull();
    expect(screen.queryByText("Transkriberingsmodell")).toBeNull();
    expect(screen.queryByText("Formulärfält")).toBeNull();

    fireEvent.click(screen.getByRole("button", { name: "Ändra inställningar" }));
    expect(
      screen.getByText(
        "Inget steg tar emot ljud just nu. Inställningarna gäller när ett steg gör det."
      )
    ).toBeTruthy();
    expect(screen.queryByRole("combobox", { name: /Transkriberingsmodell/ })).toBeNull();
    fireEvent.click(screen.getByRole("switch", { name: /Transkribera ljud/ }));
    expect(screen.getByRole("combobox", { name: /Transkriberingsmodell/ })).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Spara inställningar" }));

    await waitFor(() => expect(onSave).toHaveBeenCalledTimes(1));
    expect(onSave).toHaveBeenCalledWith(
      expect.objectContaining({ metadata_json: { wizard: { transcription_enabled: true } } })
    );
  });

  it("names the model and the language in the read view when transcription is on", () => {
    const on = makeFlow({
      metadata_json: {
        wizard: {
          transcription_enabled: true,
          transcription_model: { id: "tm-1" },
          transcription_language: "en"
        }
      }
    });
    renderInApp(<FlowSettings flow={on} canEdit transcription={resources} onSave={vi.fn()} />);
    // Under their own heading, which says it is on: no separate "På" row.
    expect(screen.getByRole("heading", { level: 3, name: "Transkribering" })).toBeTruthy();
    expect(screen.queryByText("Transkribering", { selector: "dt" })).toBeNull();
    expect(rowValue("Ljudfiler")).toBe("Tal till text");
    expect(rowValue("Språk")).toBe("English");
  });

  it("puts the labels above the values on a phone, beside them on a wider screen", () => {
    const { unmount } = renderInApp(<SettingsSummary flow={flow} />);
    // Beside: the label is a cell of the list's own two-column grid.
    expect(screen.getByText("Steg").closest("dt")?.parentElement?.tagName).toBe("DL");
    unmount();

    setViewport("phone");
    renderInApp(<SettingsSummary flow={flow} />);
    // Above: each label and value are stacked in a row of their own.
    expect(screen.getByText("Steg").closest("dt")?.parentElement?.tagName).toBe("DIV");
    expect(rowValue("Steg")).toBe("2");
  });

  it("puts the labels above the values wherever the summary itself is narrow", () => {
    renderInApp(<SettingsSummary flow={flow} />);
    const placed = () => screen.getByText("Steg").closest("dt")?.parentElement?.tagName;
    expect(placed()).toBe("DL");
    // The summary measures itself, so its own width (an element around the
    // list) is what counts, whatever the window's.
    const resize = (width: number) =>
      act(() => {
        for (let node = screen.getByText("Steg").parentElement; node; node = node.parentElement) {
          reportResize(node, { width });
        }
      });
    // A column beside the chat and the sidebar on a wide screen: too narrow for a label column.
    resize(360);
    expect(placed()).toBe("DIV");
    resize(640);
    expect(placed()).toBe("DL");
  });

  it("asks before leaving only while the form differs from the saved flow", async () => {
    const onDirtyChange = vi.fn();
    renderInApp(
      <FlowSettings
        flow={flow}
        canEdit
        transcription={noTranscription}
        onSave={vi.fn(async () => true)}
        onDirtyChange={onDirtyChange}
      />
    );
    fireEvent.click(screen.getByRole("button", { name: "Ändra inställningar" }));
    // An open form with nothing changed has nothing to lose.
    expect(asksBeforeUnload()).toBe(false);

    const name = screen.getByRole("textbox", { name: /^Namn/ });
    fireEvent.change(name, { target: { value: "Medborgarbrev 2" } });
    await waitFor(() => expect(onDirtyChange).toHaveBeenLastCalledWith(true));
    expect(asksBeforeUnload()).toBe(true);

    // Changed back, or only by a space the save trims: nothing is unsaved.
    fireEvent.change(name, { target: { value: "Medborgarbrev " } });
    await waitFor(() => expect(onDirtyChange).toHaveBeenLastCalledWith(false));
    expect(asksBeforeUnload()).toBe(false);

    fireEvent.change(name, { target: { value: "Medborgarbrev 3" } });
    await waitFor(() => expect(onDirtyChange).toHaveBeenLastCalledWith(true));
    fireEvent.click(screen.getByRole("button", { name: "Spara inställningar" }));
    await screen.findByRole("button", { name: "Ändra inställningar" });
    expect(onDirtyChange).toHaveBeenLastCalledWith(false);
    expect(asksBeforeUnload()).toBe(false);
  });

  it("refuses to save over settings the chat changed, and loads them again", async () => {
    const onSave = vi.fn(async () => true);
    const view = (current: typeof flow) => (
      <FlowSettings flow={current} canEdit transcription={noTranscription} onSave={onSave} />
    );
    const { container, rerender } = renderInApp(view(flow));
    fireEvent.click(screen.getByRole("button", { name: "Ändra inställningar" }));
    fireEvent.change(screen.getByRole("textbox", { name: /^Namn/ }), {
      target: { value: "Mitt namn" }
    });

    rerender(
      view({
        ...flow,
        draft_revision: flow.draft_revision + 1,
        description: "Chatten skrev det här."
      })
    );
    expect(await screen.findByText("Inställningarna har ändrats någon annanstans")).toBeTruthy();
    expect(announce).toHaveBeenCalledWith("Inställningarna har ändrats någon annanstans");
    await expectNoAxeViolations(container);

    // The save would overwrite the chat's description: it stays here, at the way out.
    fireEvent.click(screen.getByRole("button", { name: "Spara inställningar" }));
    const reload = screen.getByRole("button", { name: "Läs in igen" });
    await waitFor(() => expect(document.activeElement).toBe(reload));
    expect(onSave).not.toHaveBeenCalled();

    fireEvent.click(reload);
    expect(screen.queryByText("Inställningarna har ändrats någon annanstans")).toBeNull();
    const name = screen.getByRole("textbox", { name: /^Namn/ }) as HTMLInputElement;
    expect(name.value).toBe("Medborgarbrev");
    expect(
      (screen.getByRole("textbox", { name: /Beskrivning/ }) as HTMLTextAreaElement).value
    ).toBe("Chatten skrev det här.");
    await waitFor(() => expect(document.activeElement).toBe(name));
    expect(announce).toHaveBeenCalledWith("De senaste inställningarna är inlästa");

    fireEvent.click(screen.getByRole("button", { name: "Spara inställningar" }));
    await waitFor(() => expect(onSave).toHaveBeenCalledTimes(1));
  });

  it("leaves the form alone when a new revision changed no setting", () => {
    const view = (current: typeof flow) => (
      <FlowSettings flow={current} canEdit transcription={noTranscription} onSave={vi.fn()} />
    );
    const { rerender } = renderInApp(view(flow));
    fireEvent.click(screen.getByRole("button", { name: "Ändra inställningar" }));
    // A step moved: nothing in the form is out of date.
    rerender(view({ ...flow, draft_revision: flow.draft_revision + 1 }));
    expect(screen.queryByText("Inställningarna har ändrats någon annanstans")).toBeNull();
  });

  it("opens the form on request and focuses the field asked for", async () => {
    const view = (openRequest?: { nonce: number; focus?: "name" | "transcription_model" }) => (
      <FlowSettings
        flow={audioFlow}
        canEdit
        transcription={resources}
        onSave={vi.fn()}
        openRequest={openRequest}
      />
    );
    const { rerender } = renderInApp(view());
    expect(screen.queryByRole("textbox", { name: /^Namn/ })).toBeNull();

    rerender(view({ nonce: 1, focus: "transcription_model" }));
    const model = await screen.findByRole("combobox", { name: /Transkriberingsmodell/ });
    await waitFor(() => expect(document.activeElement).toBe(model));

    // Asked again with the form open: what is typed stays, focus moves.
    const name = screen.getByRole("textbox", { name: /^Namn/ }) as HTMLInputElement;
    fireEvent.change(name, { target: { value: "Pågående ändring" } });
    rerender(view({ nonce: 2, focus: "name" }));
    await waitFor(() => expect(document.activeElement).toBe(name));
    expect(name.value).toBe("Pågående ändring");
  });

  it("goes to the transcription switch when the field asked for is not shown", async () => {
    renderInApp(
      <FlowSettings
        flow={makeFlow()}
        canEdit
        transcription={resources}
        onSave={vi.fn()}
        openRequest={{ nonce: 1, focus: "speaker_service" }}
      />
    );
    const toggle = await screen.findByRole("switch", { name: /Transkribera ljud/ });
    await waitFor(() => expect(document.activeElement).toBe(toggle));
  });

  it("answers a request once, not again when the section comes back", async () => {
    const request = { nonce: 1 };
    const view = (
      <FlowSettings
        flow={flow}
        canEdit
        transcription={noTranscription}
        onSave={vi.fn()}
        openRequest={request}
      />
    );
    const { unmount } = renderInApp(view);
    await screen.findByRole("textbox", { name: /^Namn/ });
    unmount();

    renderInApp(view);
    await new Promise(requestAnimationFrame);
    expect(screen.queryByRole("textbox", { name: /^Namn/ })).toBeNull();
    expect(screen.getByRole("button", { name: "Ändra inställningar" })).toBeTruthy();
  });

  it("offers no form on request to someone who cannot edit", async () => {
    renderInApp(
      <FlowSettings
        flow={flow}
        canEdit={false}
        transcription={noTranscription}
        onSave={vi.fn()}
        openRequest={{ nonce: 1, focus: "name" }}
      />
    );
    await new Promise(requestAnimationFrame);
    expect(screen.queryByRole("textbox", { name: /^Namn/ })).toBeNull();
  });

  it("puts focus in a new field's label, and says nothing wrong before it is touched", async () => {
    renderInApp(
      <FlowSettings flow={flow} canEdit transcription={noTranscription} onSave={vi.fn()} />
    );
    fireEvent.click(screen.getByRole("button", { name: "Ändra inställningar" }));
    fireEvent.click(screen.getByRole("button", { name: "Lägg till fält" }));
    const field = screen.getByRole("group", { name: "Fält 2" });
    await waitFor(() =>
      expect(document.activeElement).toBe(within(field).getByRole("textbox", { name: /Etikett/ }))
    );
    expect(within(field).queryByText(messages.flows_field_problem_required)).toBeNull();
  });

  it("hints at a label another field of the form already has", () => {
    renderInApp(
      <FlowSettings flow={flow} canEdit transcription={noTranscription} onSave={vi.fn()} />
    );
    fireEvent.click(screen.getByRole("button", { name: "Ändra inställningar" }));
    fireEvent.click(screen.getByRole("button", { name: "Lägg till fält" }));
    const label = "Diarienummer";
    const added = within(screen.getByRole("group", { name: "Fält 2" })).getByRole("textbox", {
      name: /Etikett/
    });
    fireEvent.change(added, { target: { value: ` ${label.toLocaleUpperCase()} ` } });
    const hint = messages.flows_field_label_taken.replace("{label}", label.toLocaleUpperCase());
    expect(screen.getByText(hint)).toBeTruthy();
    // A hint, not an error: the form still saves.
    expect(added.getAttribute("aria-invalid")).not.toBe("true");
    fireEvent.change(added, { target: { value: "Något annat" } });
    expect(screen.queryByText(hint)).toBeNull();
  });

  it("explains an empty run form with an example, and adds the first field", async () => {
    const { container } = renderInApp(
      <FlowSettings flow={makeFlow()} canEdit transcription={noTranscription} onSave={vi.fn()} />
    );
    fireEvent.click(screen.getByRole("button", { name: "Ändra inställningar" }));
    expect(screen.getByText(/\{\{flow_input\.extern_referens\}\}/)).toBeTruthy();
    await expectNoAxeViolations(container);

    fireEvent.click(screen.getByRole("button", { name: "Lägg till fält" }));
    expect(screen.queryByText(/\{\{flow_input\.extern_referens\}\}/)).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Ta bort fältet Fält 1" }));
    expect(screen.getByText(/\{\{flow_input\.extern_referens\}\}/)).toBeTruthy();
    // The row is gone: the add button, now in the empty state, keeps focus in the form.
    await waitFor(() =>
      expect(document.activeElement).toBe(screen.getByRole("button", { name: "Lägg till fält" }))
    );
  });
});
