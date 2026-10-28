// @vitest-environment jsdom
import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeAll, describe, expect, it, vi } from "vitest";
import { expectNoAxeViolations } from "@/test/axe";
import { renderInApp } from "@/test/render";

const model = (id: string, nickname: string, supported: Record<string, unknown>) => ({
  id,
  name: id,
  nickname,
  org: "OpenAI",
  max_input_tokens: 128_000,
  max_output_tokens: 4_096,
  is_deprecated: false,
  vision: false,
  reasoning: false,
  supports_tool_calling: false,
  supported_model_kwargs: supported
});

const MODELS = [
  // Presets and top_p.
  model("gpt-4o", "GPT-4o", {
    temperature: { supported: true, minimum: 0, maximum: 2 },
    top_p: { supported: true, minimum: 0, maximum: 1 }
  }),
  // No temperature, so no presets; reasoning effort instead.
  model("o3", "o3", {
    temperature: { supported: false },
    reasoning_effort: { supported: true, options: ["low", "medium", "high"] }
  })
];

const api = vi.hoisted(() => ({ GET: vi.fn(), POST: vi.fn(), PATCH: vi.fn() }));
vi.mock("@/lib/api/browser", () => ({ browserApi: api }));

import { TemplateEditorDialog } from "./template-editor-dialog";
import type { AppTemplate, AssistantTemplate } from "./templates";

// Radix Select scrolls its selected option into view; jsdom has no layout.
beforeAll(() => {
  Element.prototype.scrollIntoView = () => {};
});
afterEach(() => vi.clearAllMocks());

const ok = (data: unknown) => Promise.resolve({ data, response: new Response("{}") });

function renderEditor(props: Partial<React.ComponentProps<typeof TemplateEditorDialog>>) {
  api.GET.mockImplementation(() => ok({ completion_models: MODELS }));
  api.POST.mockImplementation(() => ok({}));
  api.PATCH.mockImplementation(() => ok({}));
  return renderInApp(
    <TemplateEditorDialog kind="assistants" open onOpenChange={() => {}} {...props} />
  );
}

const base = {
  id: "t1",
  name: "Mötesprotokoll",
  description: "",
  category: "transcription",
  prompt_text: "Sammanfatta",
  completion_model_id: "gpt-4o",
  completion_model_kwargs: {},
  wizard: null,
  icon_name: null,
  created_at: "2026-10-01T09:00:00Z"
};
const appTemplate = (overrides: Partial<AppTemplate>) =>
  ({ ...base, input_type: "audio-upload", input_description: null, ...overrides }) as AppTemplate;
const assistantTemplate = { ...base, category: "advice" } as AssistantTemplate;

function lastBody(method: typeof api.POST): Record<string, unknown> {
  const [, init] = method.mock.calls.at(-1) as [string, { body: Record<string, unknown> }];
  return init.body;
}

describe("TemplateEditorDialog", () => {
  it("starts a new app template with the first model, text input and the first category", async () => {
    renderEditor({ kind: "apps" });
    const dialog = screen.getByRole("dialog", { name: "Ny mall" });
    await within(dialog).findByRole("button", { name: "Chattmodell: GPT-4o" });
    expect(within(dialog).getByRole("combobox", { name: "Inmatningstyp" }).textContent).toBe(
      "Ange text direkt"
    );
    expect(within(dialog).getByRole("combobox", { name: "Välj kategori" }).textContent).toBe(
      "Transkription"
    );

    fireEvent.change(within(dialog).getByLabelText("Mallnamn"), {
      target: { value: "Mötesprotokoll" }
    });
    fireEvent.click(within(dialog).getByRole("button", { name: "Skapa" }));

    await waitFor(() => expect(api.POST).toHaveBeenCalledTimes(1));
    expect(api.POST.mock.calls[0]![0]).toBe("/api/v1/admin/templates/apps/");
    expect(lastBody(api.POST)).toMatchObject({
      name: "Mötesprotokoll",
      category: "transcription",
      input_type: "text-field",
      completion_model_id: "gpt-4o",
      completion_model_kwargs: {},
      icon_name: null
    });
  });

  it("will not save an app template until a stored unknown input type is replaced", async () => {
    renderEditor({ kind: "apps", template: appTemplate({ input_type: "text" }) });
    const dialog = screen.getByRole("dialog", { name: "Redigera mall" });
    const inputType = await within(dialog).findByRole("combobox", { name: "Inmatningstyp" });
    expect(inputType.textContent).toBe("Inget valt");

    fireEvent.click(within(dialog).getByRole("button", { name: "Spara" }));

    expect(inputType.getAttribute("aria-invalid")).toBe("true");
    expect(within(dialog).getByText("Indatatyp krävs för appmallar")).toBeTruthy();
    expect(document.activeElement).toBe(inputType);
    expect(api.PATCH).not.toHaveBeenCalled();

    fireEvent.keyDown(inputType, { key: "Enter" });
    fireEvent.click(await screen.findByRole("option", { name: "Ladda upp ljudfil" }));
    fireEvent.click(within(dialog).getByRole("button", { name: "Spara" }));
    await waitFor(() => expect(api.PATCH).toHaveBeenCalledTimes(1));
    expect(lastBody(api.PATCH)).toMatchObject({ input_type: "audio-upload" });
  });

  it("shows each problem at its field on submit, and moves focus to the first", async () => {
    renderEditor({ kind: "assistants" });
    const dialog = screen.getByRole("dialog", { name: "Ny mall" });
    const create = await within(dialog).findByRole("button", { name: "Skapa" });
    // Never disabled: a disabled button says nothing about what is missing.
    expect((create as HTMLButtonElement).disabled).toBe(false);

    fireEvent.click(create);
    const name = within(dialog).getByLabelText("Mallnamn");
    expect(name.getAttribute("aria-invalid")).toBe("true");
    expect(document.activeElement).toBe(name);

    fireEvent.change(name, { target: { value: "Upphandlingsstöd" } });
    // A custom category starts empty and must be named.
    fireEvent.click(within(dialog).getByRole("radio", { name: "Anpassad" }));
    fireEvent.click(create);
    const custom = within(dialog).getByRole("textbox", { name: "Kategori" });
    expect(name.getAttribute("aria-invalid")).toBeNull();
    expect(custom.getAttribute("aria-invalid")).toBe("true");
    expect(within(dialog).getByText("Kategori krävs")).toBeTruthy();
    expect(document.activeElement).toBe(custom);
    expect(api.POST).not.toHaveBeenCalled();
    await expectNoAxeViolations(dialog);

    // Back to the predefined list: its choice is kept.
    fireEvent.click(within(dialog).getByRole("radio", { name: "Fördefinierad" }));
    expect(within(dialog).getByRole("combobox", { name: "Välj kategori" }).textContent).toBe(
      "Kommunikation"
    );
  });

  it("sets the temperature from a behaviour preset", async () => {
    renderEditor({ kind: "assistants" });
    const dialog = screen.getByRole("dialog", { name: "Ny mall" });
    fireEvent.change(await within(dialog).findByLabelText("Mallnamn"), {
      target: { value: "Skrivhjälp" }
    });
    fireEvent.keyDown(within(dialog).getByRole("combobox", { name: "Modellbeteende" }), {
      key: "Enter"
    });
    fireEvent.click(await screen.findByRole("option", { name: "Kreativ" }));
    fireEvent.click(within(dialog).getByRole("button", { name: "Skapa" }));

    await waitFor(() => expect(api.POST).toHaveBeenCalledTimes(1));
    expect(lastBody(api.POST)).toMatchObject({
      category: "communication",
      completion_model_kwargs: { temperature: 1.25 }
    });
  });

  it("disables presets for a model without temperature and drops what it does not take", async () => {
    renderEditor({
      kind: "apps",
      template: appTemplate({
        completion_model_id: "o3",
        completion_model_kwargs: { temperature: 0.25, top_p: 0.5, reasoning_effort: "high" }
      })
    });
    const dialog = screen.getByRole("dialog", { name: "Redigera mall" });
    const behaviour = await within(dialog).findByRole("combobox", { name: "Modellbeteende" });
    expect(behaviour.hasAttribute("disabled")).toBe(true);
    expect(behaviour.textContent).toBe("Standard");
    expect(
      within(dialog).getByText(
        "Den här modellen använder modellspecifika parametrar istället för beteendepresets."
      ).id
    ).toBe(behaviour.getAttribute("aria-describedby"));
    expect(within(dialog).getByRole("combobox", { name: "Resonemangsnivå" })).toBeTruthy();

    fireEvent.click(within(dialog).getByRole("button", { name: "Spara" }));
    await waitFor(() => expect(api.PATCH).toHaveBeenCalledTimes(1));
    expect(lastBody(api.PATCH).completion_model_kwargs).toEqual({ reasoning_effort: "high" });
  });

  it("picks the icon by searching, shows it, and can clear it", async () => {
    renderEditor({ kind: "assistants" });
    const dialog = screen.getByRole("dialog", { name: "Ny mall" });
    fireEvent.click(await within(dialog).findByRole("button", { name: "Välj mallikon" }));

    const picker = await screen.findByRole("dialog", { name: "Välj en ikon" });
    // Popular icons come first.
    expect(within(picker).getByRole("button", { name: "Välj ikon: rocket" })).toBeTruthy();
    fireEvent.change(
      within(picker).getByLabelText("Sök ikoner... (t.ex. 'raket', 'mejl', 'diagram')"),
      { target: { value: "Message Square" } }
    );
    fireEvent.click(within(picker).getByRole("button", { name: "Välj ikon: message-square" }));

    const chosen = await within(dialog).findByRole("button", {
      name: "Ändra ikon, nuvarande: message-square"
    });
    // The chosen icon is drawn once its chunk has loaded.
    await waitFor(() => expect(chosen.querySelector("svg.lucide-message-square")).toBeTruthy());

    fireEvent.click(chosen);
    const again = await screen.findByRole("dialog", { name: "Välj en ikon" });
    fireEvent.click(within(again).getByRole("button", { name: "Rensa val" }));
    expect(await within(dialog).findByRole("button", { name: "Välj mallikon" })).toBeTruthy();
  });

  it("explains each wizard step behind a help button", async () => {
    renderEditor({ kind: "assistants", template: assistantTemplate });
    const dialog = screen.getByRole("dialog", { name: "Redigera mall" });
    expect(await within(dialog).findByRole("button", { name: "Hjälp: Filbilagor" })).toBeTruthy();
    expect(within(dialog).getByRole("button", { name: "Hjälp: Kunskapssamlingar" })).toBeTruthy();
  });
});
