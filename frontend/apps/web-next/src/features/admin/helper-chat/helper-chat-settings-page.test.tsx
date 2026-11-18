// @vitest-environment jsdom
import { cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { FLOW_SETTINGS_KEY } from "@/features/admin/flow-settings/flow-settings";
import { expectNoAxeViolations } from "@/test/axe";
import { recordAnnouncements, renderInApp, testAppContext, testQueryClient } from "@/test/render";
import { HELPER_CHAT_POLICY_KEY, type HelperChatPolicy } from "./helper-chat-policy";
import { HelperChatSettingsPage } from "./helper-chat-settings-page";

const api = vi.hoisted(() => ({ GET: vi.fn(), PATCH: vi.fn() }));
vi.mock("@/lib/api/browser", () => ({ browserApi: api }));
vi.mock("@/lib/navigation", () => import("@/test/navigation"));
const toastApiError = vi.hoisted(() => vi.fn());
vi.mock("@/lib/api/toast", () => ({ toastApiError }));

const POLICY_PATH = "/api/v1/settings/helper-chat-policy";
const MODELS_PATH = "/api/v1/ai-models/";

const catalogModel = (id: string, nickname: string, overrides: Record<string, unknown> = {}) => ({
  id,
  name: id,
  nickname,
  org: "OpenAI",
  max_input_tokens: 128_000,
  max_output_tokens: 4096,
  is_deprecated: false,
  is_org_enabled: true,
  can_access: true,
  vision: false,
  reasoning: false,
  supports_tool_calling: true,
  ...overrides
});
const CATALOG = {
  completion_models: [
    catalogModel("gpt-strong", "Stark modell"),
    catalogModel("gpt-plain", "Utan verktyg", { supports_tool_calling: false }),
    catalogModel("gpt-off", "Avstängd modell", { is_org_enabled: false }),
    catalogModel("gpt-old", "Gammal modell", { is_deprecated: true }),
    catalogModel("gpt-locked", "Låst modell", { can_access: false })
  ],
  embedding_models: [],
  transcription_models: [],
  image_models: []
};

const ok = (data: unknown) => Promise.resolve({ data, response: new Response("{}") });
const refused = (status: number, error: unknown) =>
  Promise.resolve({ error, response: new Response("{}", { status }) });

function policyFixture(overrides: Partial<HelperChatPolicy> = {}): HelperChatPolicy {
  return {
    enabled: true,
    guidance: "Tilltala med du.",
    guidance_max_length: 4000,
    completion_model_id: null,
    ...overrides
  };
}

let current: HelperChatPolicy;

/** Serves the policy and answers a PATCH with its body applied, as the backend resolves it. */
function serve(policy: HelperChatPolicy) {
  current = policy;
  api.GET.mockImplementation((path: string) => ok(path === MODELS_PATH ? CATALOG : current));
  api.PATCH.mockImplementation((_path: string, { body }: { body: Partial<HelperChatPolicy> }) => {
    current = {
      ...current,
      ...body,
      ...(typeof body.guidance === "string" ? { guidance: body.guidance.trim() } : {})
    };
    return ok(current);
  });
}

beforeEach(() => serve(policyFixture()));
afterEach(() => {
  cleanup();
  vi.resetAllMocks();
});

async function show(options: Parameters<typeof renderInApp>[1] = {}) {
  const view = renderInApp(<HelperChatSettingsPage />, {
    appContext: testAppContext({ permissions: ["admin"] }),
    ...options
  });
  await screen.findByRole("textbox", { name: "Organisationens riktlinjer" });
  return view;
}

/** The text of everything that describes `element`. */
function description(element: Element): string {
  return (element.getAttribute("aria-describedby") ?? "")
    .split(" ")
    .map((id) => document.getElementById(id)?.textContent ?? "")
    .join(" ");
}

const guidanceField = () =>
  screen.getByRole<HTMLTextAreaElement>("textbox", { name: "Organisationens riktlinjer" });
/** The guidance's form, where its save state is shown (the live region says it too). */
const guidanceForm = () => within(guidanceField().closest("form") as HTMLElement);
const modelPicker = (value: string) =>
  screen.findByRole("button", { name: `Standardmodell för hjälpassistenten ${value}` });

/** Opens the picker and waits for the list to take focus, as a person would before choosing. */
async function openPicker(value: string) {
  fireEvent.click(await modelPicker(value));
  const search = await screen.findByRole("combobox", { name: "Sökalternativ" });
  await waitFor(() => expect(document.activeElement).toBe(search));
}

describe("the helper's settings page", { timeout: 20_000 }, () => {
  it("shows the three settings from the policy without axe violations", async () => {
    const { container } = await show();

    expect(screen.getByRole("heading", { level: 1, name: "Hjälpassistent" })).toBeTruthy();
    expect(screen.getAllByRole("heading", { level: 1 })).toHaveLength(1);
    for (const name of ["Tillgång", "Modell", "Riktlinjer"])
      expect(screen.getByRole("heading", { level: 2, name })).toBeTruthy();

    const toggle = screen.getByRole("switch", { name: "Hjälpassistenten är på" });
    expect((toggle as HTMLInputElement).checked).toBe(true);
    expect(description(toggle)).toContain(
      "När den är av kan ingen i organisationen öppna hjälpassistenten"
    );

    const picker = await modelPicker("Ytans standardmodell");
    expect(description(picker)).toContain(
      "Flödesassistenten har samma standardmodell, så en ändring här ändrar den även där."
    );

    const field = guidanceField();
    expect(field.value).toBe("Tilltala med du.");
    expect(field.getAttribute("placeholder")).toContain("Tilltala alltid personen med du.");
    // The counter describes the field, against the maximum the API reports.
    expect(description(field)).toContain("kan inte ändra vad den får göra");
    expect(description(field)).toMatch(/16\/4\s000/);
    await expectNoAxeViolations(container);
  });

  it("shows a failed read with a retry that loads the page", async () => {
    api.GET.mockImplementation((path: string) =>
      path === MODELS_PATH ? ok(CATALOG) : refused(500, { message: "Boom", error_id: "e-1" })
    );
    renderInApp(<HelperChatSettingsPage />);
    const retry = await screen.findByRole("button", { name: /^Försök igen/ });
    expect(screen.queryByRole("switch")).toBeNull();

    serve(policyFixture());
    fireEvent.click(retry);

    expect(await screen.findByRole("switch", { name: "Hjälpassistenten är på" })).toBeTruthy();
  });

  describe("the switch", () => {
    it("saves only whether the helper is on", async () => {
      await show();
      const toggle = screen.getByRole("switch", { name: "Hjälpassistenten är på" });

      fireEvent.click(toggle);

      await waitFor(() =>
        expect(api.PATCH).toHaveBeenCalledExactlyOnceWith(POLICY_PATH, {
          body: { enabled: false }
        })
      );
      await waitFor(() => expect((toggle as HTMLInputElement).checked).toBe(false));
      expect(toastApiError).not.toHaveBeenCalled();
    });

    it("goes back to the saved value and says why when the save fails", async () => {
      await show();
      api.PATCH.mockImplementation(() => refused(500, { message: "Boom", error_id: "e-1" }));
      const toggle = screen.getByRole("switch", { name: "Hjälpassistenten är på" });
      toggle.focus();

      fireEvent.click(toggle);

      await waitFor(() => expect(toastApiError).toHaveBeenCalledTimes(1));
      await waitFor(() => expect((toggle as HTMLInputElement).checked).toBe(true));
      expect(document.activeElement).toBe(toggle);
    });
  });

  describe("the default model", () => {
    it("offers only the organisation's usable models that can use tools", async () => {
      await show();
      await openPicker("Ytans standardmodell");

      const options = screen.getAllByRole("option");
      expect(options.map((option) => option.textContent)).toEqual([
        expect.stringContaining("Ytans standardmodell"),
        expect.stringContaining("Stark modell")
      ]);
    });

    it("saves a chosen model, and null for the space's default, and says so", async () => {
      const said = recordAnnouncements();
      const queryClient = testQueryClient();
      queryClient.setQueryData(FLOW_SETTINGS_KEY, {});
      await show({ queryClient, appContext: testAppContext({ permissions: ["admin"] }) });
      await openPicker("Ytans standardmodell");

      fireEvent.click(screen.getByRole("option", { name: /Stark modell/ }));

      await waitFor(() =>
        expect(api.PATCH).toHaveBeenLastCalledWith(POLICY_PATH, {
          body: { completion_model_id: "gpt-strong" }
        })
      );
      await modelPicker("Stark modell");
      await waitFor(() => expect(said.join(" ")).toContain("Standardmodellen är sparad."));
      // The flow chat's settings hold the same value and are read again.
      expect(queryClient.getQueryState(FLOW_SETTINGS_KEY)?.isInvalidated).toBe(true);

      await openPicker("Stark modell");
      fireEvent.click(screen.getByRole("option", { name: /Ytans standardmodell/ }));

      await waitFor(() =>
        expect(api.PATCH).toHaveBeenLastCalledWith(POLICY_PATH, {
          body: { completion_model_id: null }
        })
      );
      await modelPicker("Ytans standardmodell");
      expect(api.PATCH).toHaveBeenCalledTimes(2);
    });

    it.each([
      [
        "helper_chat_policy_model_unavailable",
        "Modellen är inte aktiverad i organisationen. Välj en annan modell."
      ],
      [
        "helper_chat_policy_model_without_tools",
        "Modellen kan inte använda verktyg, och det behöver hjälpassistenten. Välj en annan modell."
      ]
    ])(
      "shows the refusal %s in words at the field and keeps the saved model",
      async (code, text) => {
        const said = recordAnnouncements();
        await show();
        await openPicker("Ytans standardmodell");
        api.PATCH.mockImplementation(() =>
          refused(400, { message: "Refused", eneo_error_code: 9002, code })
        );

        fireEvent.click(screen.getByRole("option", { name: /Stark modell/ }));

        const picker = await modelPicker("Ytans standardmodell");
        await waitFor(() => expect(description(picker)).toContain(text));
        await waitFor(() => expect(said.join(" ")).toContain(text));
        expect(current.completion_model_id).toBeNull();
        await expectNoAxeViolations(document.body);
      }
    );

    it("links to the flow chat's setting only when the organisation has flows", async () => {
      await show();
      expect(screen.queryByRole("link", { name: "Flödesassistentens inställningar" })).toBeNull();
      cleanup();

      await show({
        appContext: testAppContext({ permissions: ["admin"], settings: { flows_enabled: true } })
      });
      const link = screen.getByRole("link", { name: "Flödesassistentens inställningar" });
      expect(link.getAttribute("href")).toBe("/admin/flow-settings#flow-chat");
      expect(link.className).toContain("pointer-coarse:min-h-11");
    });
  });

  describe("the guidance", () => {
    it("saves the text with its Save and shows the save state", async () => {
      const said = recordAnnouncements();
      const { queryClient } = await show();
      const field = guidanceField();

      fireEvent.change(field, { target: { value: "  Svara kort.\nTilltala med du.  " } });
      expect(guidanceForm().getByText("Osparade ändringar")).toBeTruthy();
      expect(api.PATCH).not.toHaveBeenCalled();

      fireEvent.click(screen.getByRole("button", { name: "Spara riktlinjer" }));

      await waitFor(() =>
        expect(api.PATCH).toHaveBeenCalledExactlyOnceWith(POLICY_PATH, {
          body: { guidance: "  Svara kort.\nTilltala med du.  " }
        })
      );
      // The text as the server keeps it, with nothing left unsaved.
      await waitFor(() => expect(field.value).toBe("Svara kort.\nTilltala med du."));
      expect(guidanceForm().getByText("Riktlinjerna är sparade.")).toBeTruthy();
      expect(guidanceForm().queryByText("Osparade ändringar")).toBeNull();
      await waitFor(() => expect(said.join(" ")).toContain("Riktlinjerna är sparade."));
      expect(queryClient.getQueryData(HELPER_CHAT_POLICY_KEY)).toMatchObject({
        guidance: "Svara kort.\nTilltala med du."
      });
    });

    it("says there is nothing to save and sends nothing for unchanged text", async () => {
      const said = recordAnnouncements();
      await show();

      fireEvent.click(screen.getByRole("button", { name: "Spara riktlinjer" }));

      expect(guidanceForm().getByText("Inga ändringar att spara.")).toBeTruthy();
      await waitFor(() => expect(said.join(" ")).toContain("Inga ändringar att spara."));
      expect(api.PATCH).not.toHaveBeenCalled();
    });

    it("holds the text to the maximum the API reports and shows the problem at the field", async () => {
      serve(policyFixture({ guidance: "", guidance_max_length: 20 }));
      const { container } = await show();
      const field = guidanceField();
      expect(description(field)).toMatch(/0\/20/);

      fireEvent.change(field, { target: { value: "Tjugofem tecken lång text" } });
      fireEvent.click(screen.getByRole("button", { name: "Spara riktlinjer" }));

      expect(document.activeElement).toBe(field);
      expect(field.getAttribute("aria-invalid")).toBe("true");
      expect(description(field)).toContain("Texten är för lång. Korta den till högst 20 tecken.");
      expect(api.PATCH).not.toHaveBeenCalled();
      await expectNoAxeViolations(container);

      // Short enough again, it saves.
      fireEvent.change(field, { target: { value: "Tjugo tecken precis" } });
      expect(description(field)).not.toContain("Texten är för lång");
      fireEvent.click(screen.getByRole("button", { name: "Spara riktlinjer" }));
      await waitFor(() =>
        expect(api.PATCH).toHaveBeenCalledExactlyOnceWith(POLICY_PATH, {
          body: { guidance: "Tjugo tecken precis" }
        })
      );
    });

    it("shows a refused save at the field and keeps the text", async () => {
      await show();
      api.PATCH.mockImplementation(() =>
        refused(422, {
          message: "Request validation failed",
          code: "request_validation_error",
          details: { errors: [{ location: ["body", "guidance"], type: "string_too_long" }] }
        })
      );
      const field = guidanceField();
      fireEvent.change(field, { target: { value: "Nya riktlinjer" } });

      fireEvent.click(screen.getByRole("button", { name: "Spara riktlinjer" }));

      await waitFor(() => expect(document.activeElement).toBe(field));
      expect(field.getAttribute("aria-invalid")).toBe("true");
      expect(description(field)).toContain(
        "Texten är för lång. Korta den till högst 4 000 tecken."
      );
      expect(field.value).toBe("Nya riktlinjer");
      expect(guidanceForm().getByText("Osparade ändringar")).toBeTruthy();
    });

    it("shows a failed save at the field with what to do, and the text stays", async () => {
      await show();
      api.PATCH.mockImplementation(() => refused(500, { message: "Boom", error_id: "e-1" }));
      const field = guidanceField();
      fireEvent.change(field, { target: { value: "Nya riktlinjer" } });

      fireEvent.click(screen.getByRole("button", { name: "Spara riktlinjer" }));

      await waitFor(() =>
        expect(description(field)).toContain("Texten finns kvar, så du kan försöka spara igen.")
      );
      expect(document.activeElement).toBe(field);
      expect(field.value).toBe("Nya riktlinjer");
      // Typing again clears the refusal.
      fireEvent.change(field, { target: { value: "Nya riktlinjer!" } });
      expect(field.getAttribute("aria-invalid")).toBeNull();
    });

    it("puts back the saved text when the changes are discarded", async () => {
      await show();
      const field = guidanceField();
      const discard = screen.getByRole("button", { name: "Ignorera ändringar" });
      expect(discard.getAttribute("aria-disabled")).toBe("true");
      fireEvent.change(field, { target: { value: "Något annat" } });
      expect(discard.getAttribute("aria-disabled")).toBeNull();

      fireEvent.click(discard);

      expect(field.value).toBe("Tilltala med du.");
      expect(guidanceForm().queryByText("Osparade ändringar")).toBeNull();
      expect(api.PATCH).not.toHaveBeenCalled();
    });

    it("follows a guidance saved elsewhere while the field is untouched", async () => {
      const { queryClient } = await show();
      const field = guidanceField();

      queryClient.setQueryData(HELPER_CHAT_POLICY_KEY, policyFixture({ guidance: "Ny text." }));

      await waitFor(() => expect(field.value).toBe("Ny text."));
      expect(guidanceForm().queryByText("Osparade ändringar")).toBeNull();
    });
  });
});
