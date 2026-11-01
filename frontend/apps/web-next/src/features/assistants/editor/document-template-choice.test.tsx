// @vitest-environment jsdom
import { useQuery } from "@tanstack/react-query";
import { act, cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import type { Schema } from "@/lib/api/models";
import { browserApi } from "@/lib/api/browser";
import { SaveStatusProvider, SaveStatusIndicator } from "@/components/composites/save-status";
import { useAutosave } from "@/components/composites/use-autosave";
import { expectNoAxeViolations } from "@/test/axe";
import messages from "@/lib/i18n/messages/sv.json";
import { renderInApp, testQueryClient } from "@/test/render";
import { CapabilitiesSection } from "./capabilities-section";
import { AssistantDocumentTemplateChoice } from "./document-template-choice";
import {
  assistantQueryOptions,
  useUpdateAssistant,
  type Assistant,
  type AssistantUpdate
} from "./use-assistant";

const api = vi.hoisted(() => ({ GET: vi.fn(), POST: vi.fn() }));
vi.mock("@/lib/api/browser", () => ({ browserApi: api }));
vi.mock("@/features/spaces/use-space", () => ({
  useSpace: () => ({
    routeId: "space-1",
    space: { enabled_capabilities: ["file_creation"], completion_models: [] }
  })
}));

const initial: Assistant = {
  id: "assistant-1",
  name: "Avtalsassistenten",
  space_id: "space-1",
  permissions: ["read", "edit"],
  enabled_capabilities: ["file_creation"],
  document_template: { mode: "builtin", template_id: null },
  completion_model_kwargs: {},
  logging_enabled: true,
  attachments: [],
  allowed_attachments: { accepted_file_types: [], limit: { max_files: 10, max_size: 1000 } },
  groups: [],
  websites: [],
  integration_knowledge_list: [],
  user: { id: "user-1", email: "user@example.se" },
  tools: { assistants: [] },
  type: "assistant",
  insight_enabled: false,
  inline_file_text: true,
  knowledge_mode: "tool"
};
const options: Schema<"DocumentTemplateOptions"> = {
  items: [
    { id: "report", name: "Rapport", is_default: false },
    { id: "municipal", name: "Kommunens mall", is_default: true }
  ]
};
const ok = (data: unknown) => ({ data, response: new Response() });
let saved: Assistant;
beforeEach(() => {
  api.GET.mockReset();
  api.POST.mockReset();
  saved = structuredClone(initial);
  api.GET.mockImplementation(async () => ok(options));
  api.POST.mockImplementation(async (_path: string, init: { body: AssistantUpdate }) => {
    saved = { ...saved, document_template: init.body.document_template ?? saved.document_template };
    return ok(saved);
  });
});
afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

function Harness({
  id = "assistant-1",
  capabilities = false
}: {
  id?: string;
  capabilities?: boolean;
}) {
  const { data } = useQuery(assistantQueryOptions(browserApi, id));
  return data ? (
    capabilities ? (
      <CapabilitiesSection key={id} assistant={data} />
    ) : (
      <AssistantDocumentTemplateChoice key={id} assistant={data} />
    )
  ) : null;
}
function show(value = saved) {
  const queryClient = testQueryClient();
  queryClient.setQueryData(assistantQueryOptions(browserApi, value.id).queryKey, value);
  return { ...renderInApp(<Harness id={value.id} />, { queryClient }), queryClient };
}

it("saves explicit default, selected and built-in choices through the assistant owner", async () => {
  show();
  expect(await screen.findByText("Dokumentmall: Eneos inbyggda mall")).toBeTruthy();
  fireEvent.click(screen.getByRole("button", { name: "Ändra dokumentmall" }));
  fireEvent.click(screen.getByRole("radio", { name: /Organisationens standard/ }));
  await waitFor(() =>
    expect(saved.document_template).toEqual({ mode: "default", template_id: null })
  );
  fireEvent.click(screen.getByRole("radio", { name: "En annan mall" }));
  await waitFor(() =>
    expect(saved.document_template).toEqual({ mode: "selected", template_id: "municipal" })
  );
  fireEvent.click(screen.getByRole("radio", { name: "Eneos inbyggda mall" }));
  await waitFor(() =>
    expect(saved.document_template).toEqual({ mode: "builtin", template_id: null })
  );
  expect(
    api.POST.mock.calls.map((call) => [call[0], call[1].params.path.id, call[1].body])
  ).toEqual([
    [
      "/api/v1/assistants/{id}/",
      "assistant-1",
      { document_template: { mode: "default", template_id: null } }
    ],
    [
      "/api/v1/assistants/{id}/",
      "assistant-1",
      { document_template: { mode: "selected", template_id: "municipal" } }
    ],
    [
      "/api/v1/assistants/{id}/",
      "assistant-1",
      { document_template: { mode: "builtin", template_id: null } }
    ]
  ]);
});

it.each([true, false])(
  "preserves a saved selection and returns read-retry focus with editable=%s",
  async (editable) => {
    saved.permissions = editable ? ["read", "edit"] : ["read"];
    saved.document_template = { mode: "selected", template_id: "report" };
    api.GET.mockResolvedValueOnce({
      data: undefined,
      error: { message: "Options unavailable" },
      response: new Response(null, { status: 503 })
    });
    show();
    const retry = await screen.findByRole("button", { name: "Försök igen" });
    retry.focus();
    fireEvent.click(retry);
    expect(await screen.findByText("Dokumentmall: Rapport")).toBeTruthy();
    await waitFor(() =>
      expect(document.activeElement).toBe(screen.getByText("Dokumentmall: Rapport"))
    );
    expect(saved.document_template).toEqual({ mode: "selected", template_id: "report" });
    expect(api.POST).not.toHaveBeenCalled();
    expect(api.GET.mock.calls.map((call) => call[0])).toEqual([
      "/api/v1/document-templates/available/",
      "/api/v1/document-templates/available/"
    ]);
  }
);

it("keeps a failed choice available for retry while the saved assistant stays unchanged", async () => {
  api.POST.mockResolvedValueOnce({
    data: undefined,
    error: { message: "Cannot save this choice" },
    response: new Response(null, { status: 503 })
  });
  let finish!: () => void;
  api.POST.mockImplementationOnce(
    (_path: string, init: { body: AssistantUpdate }) =>
      new Promise<ReturnType<typeof ok>>((resolve) => {
        finish = () => {
          saved = {
            ...saved,
            document_template: init.body.document_template ?? saved.document_template
          };
          resolve(ok(saved));
        };
      })
  );
  const { queryClient } = show();
  await screen.findByText("Dokumentmall: Eneos inbyggda mall");
  fireEvent.click(screen.getByRole("button", { name: "Ändra dokumentmall" }));
  await screen.findByText("Kommunens mall");
  fireEvent.click(screen.getByRole("radio", { name: "En annan mall" }));
  await waitFor(() => expect(api.POST).toHaveBeenCalledTimes(1));
  const retry = await screen.findByRole("button", {
    name: "Försök igen: Kunde inte spara ändringarna"
  });
  expect(screen.getByRole("radio", { name: "En annan mall", checked: true })).toBeTruthy();
  expect(
    queryClient.getQueryData<Assistant>(assistantQueryOptions(browserApi, saved.id).queryKey)
      ?.document_template
  ).toEqual(initial.document_template);
  retry.focus();
  fireEvent.click(retry);
  await waitFor(() => expect(retry.getAttribute("aria-busy")).toBe("true"));
  expect(document.activeElement).toBe(retry);
  fireEvent.click(retry);
  expect(api.POST).toHaveBeenCalledTimes(2);
  await act(async () => finish());
  await waitFor(() =>
    expect(document.activeElement).toBe(screen.getByRole("button", { name: "Ändra dokumentmall" }))
  );
  await waitFor(() =>
    expect(saved.document_template).toEqual({ mode: "selected", template_id: "municipal" })
  );
  expect(api.POST).toHaveBeenCalledTimes(2);
  for (const call of api.POST.mock.calls)
    expect(call[1].body).toEqual({
      document_template: { mode: "selected", template_id: "municipal" }
    });
});

it("disables named-template choice for an empty library while default and built-in remain usable", async () => {
  api.GET.mockResolvedValue(ok({ items: [] }));
  show();
  fireEvent.click(screen.getByRole("button", { name: "Ändra dokumentmall" }));
  await screen.findByText("Organisationen har inga egna mallar ännu.");
  const selected = screen.getByRole("radio", { name: "En annan mall" });
  expect(selected.hasAttribute("disabled")).toBe(true);
  fireEvent.click(selected);
  expect(api.POST).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole("radio", { name: /Organisationens standard/ }));
  await waitFor(() =>
    expect(saved.document_template).toEqual({ mode: "default", template_id: null })
  );
  fireEvent.click(screen.getByRole("radio", { name: "Eneos inbyggda mall" }));
  await waitFor(() =>
    expect(saved.document_template).toEqual({ mode: "builtin", template_id: null })
  );
});

it("shows a read-only saved selection without edit controls or implicit writes", async () => {
  saved = {
    ...saved,
    permissions: ["read"],
    document_template: { mode: "selected", template_id: "report" }
  };
  const { container } = show();
  await screen.findByText("Dokumentmall: Rapport");
  expect(screen.queryByRole("button", { name: "Ändra dokumentmall" })).toBeNull();
  expect(
    screen.getByText("Du behöver redigeringsbehörighet för att ändra dokumentmall.")
  ).toBeTruthy();
  expect(api.POST).not.toHaveBeenCalled();
  await expectNoAxeViolations(container);
});

it("retains the current named selection and saves a different named template explicitly", async () => {
  saved.document_template = { mode: "selected", template_id: "report" };
  const { container } = show();
  await screen.findByText("Dokumentmall: Rapport");
  expect(api.POST).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole("button", { name: "Ändra dokumentmall" }));
  const selector = screen.getByRole("combobox", { name: "En annan mall" });
  expect(selector.textContent).toContain("Rapport");
  fireEvent.click(selector);
  fireEvent.click(await screen.findByRole("option", { name: "Kommunens mall" }));
  await waitFor(() =>
    expect(saved.document_template).toEqual({ mode: "selected", template_id: "municipal" })
  );
  await expectNoAxeViolations(container);
});

it("uses the first available template when no organisation default exists", async () => {
  api.GET.mockResolvedValue(ok({ items: [options.items[0]!] }));
  show();
  fireEvent.click(screen.getByRole("button", { name: "Ändra dokumentmall" }));
  await screen.findByText("Organisationens standard");
  await waitFor(() =>
    expect(screen.getByRole("radio", { name: "En annan mall" }).hasAttribute("disabled")).toBe(
      false
    )
  );
  fireEvent.click(screen.getByRole("radio", { name: "En annan mall" }));
  await waitFor(() =>
    expect(saved.document_template).toEqual({ mode: "selected", template_id: "report" })
  );
});

it("keeps a pending save on its captured assistant after the editor changes resource", async () => {
  let finish!: (result: ReturnType<typeof ok>) => void;
  api.POST.mockImplementationOnce(
    () =>
      new Promise<ReturnType<typeof ok>>((resolve) => {
        finish = resolve;
      })
  );
  const view = show();
  const other: Assistant = { ...initial, id: "assistant-2", name: "En annan assistent" };
  view.queryClient.setQueryData(assistantQueryOptions(browserApi, other.id).queryKey, other);
  fireEvent.click(screen.getByRole("button", { name: "Ändra dokumentmall" }));
  fireEvent.click(screen.getByRole("radio", { name: /Organisationens standard/ }));
  await waitFor(() => expect(api.POST).toHaveBeenCalledTimes(1));
  view.rerender(<Harness id={other.id} />);
  await act(async () =>
    finish(ok({ ...initial, document_template: { mode: "default", template_id: null } }))
  );
  await waitFor(() =>
    expect(
      view.queryClient.getQueryData<Assistant>(
        assistantQueryOptions(browserApi, initial.id).queryKey
      )?.document_template?.mode
    ).toBe("default")
  );
  expect(
    view.queryClient.getQueryData<Assistant>(assistantQueryOptions(browserApi, other.id).queryKey)
      ?.document_template
  ).toEqual(initial.document_template);
  expect(screen.getByText("Dokumentmall: Eneos inbyggda mall")).toBeTruthy();
  expect(api.POST.mock.calls[0]![1].params.path.id).toBe(initial.id);
});

function CapabilitySaveProbe() {
  const update = useUpdateAssistant("assistant-1");
  const autosave = useAutosave("capabilities");
  return (
    <button
      onClick={() =>
        void autosave(() =>
          update.mutateAsync({ enabled_capabilities: ["file_creation", "charts"] })
        )
      }
    >
      Save capabilities
    </button>
  );
}

it("keeps serial field saves pending and their failures separate in the actual page status owner", async () => {
  let finishCapability!: () => void;
  let finishTemplate: (() => void) | undefined;
  api.POST.mockImplementationOnce(
    () =>
      new Promise<ReturnType<typeof ok>>((resolve) => {
        finishCapability = () => {
          saved = { ...saved, enabled_capabilities: ["file_creation", "charts"] };
          resolve(ok(saved));
        };
      })
  );
  api.POST.mockImplementationOnce(
    () =>
      new Promise<ReturnType<typeof ok>>((resolve) => {
        finishTemplate = () => {
          saved = { ...saved, document_template: { mode: "default", template_id: null } };
          resolve(ok(saved));
        };
      })
  );
  const queryClient = testQueryClient();
  queryClient.setQueryData(assistantQueryOptions(browserApi, saved.id).queryKey, saved);
  renderInApp(
    <SaveStatusProvider>
      <header>
        <SaveStatusIndicator />
      </header>
      <CapabilitySaveProbe />
      <Harness />
    </SaveStatusProvider>,
    { queryClient }
  );
  const status = within(screen.getByRole("banner"));
  fireEvent.click(screen.getByRole("button", { name: "Save capabilities" }));
  await waitFor(() => expect(api.POST).toHaveBeenCalledTimes(1));
  fireEvent.click(screen.getByRole("button", { name: "Ändra dokumentmall" }));
  fireEvent.click(screen.getByRole("radio", { name: /Organisationens standard/ }));
  expect(api.POST).toHaveBeenCalledTimes(1);
  await act(async () => finishCapability());
  await waitFor(() => expect(api.POST).toHaveBeenCalledTimes(2));
  try {
    expect(status.getByText("Sparar…")).toBeTruthy();
    const beforeUnload = new Event("beforeunload", { cancelable: true });
    window.dispatchEvent(beforeUnload);
    expect(beforeUnload.defaultPrevented).toBe(true);
  } finally {
    await act(async () => finishTemplate?.());
  }
  await status.findByText(messages.all_changes_saved);
  api.POST.mockResolvedValueOnce({
    data: undefined,
    error: { message: "Template save failed" },
    response: new Response(null, { status: 503 })
  });
  fireEvent.click(screen.getByRole("radio", { name: "En annan mall" }));
  await screen.findByRole("button", { name: "Försök igen: Kunde inte spara ändringarna" });
  fireEvent.click(screen.getByRole("button", { name: "Save capabilities" }));
  await waitFor(() => expect(api.POST).toHaveBeenCalledTimes(4));
  await waitFor(() =>
    expect(
      status.getByRole("link", { name: "Kunde inte spara ändringarna" }).getAttribute("href")
    ).toBe("#assistant-document-template")
  );
  expect(document.getElementById("assistant-document-template")).not.toBeNull();
});

it("restores readonly focus after retrying a failed refresh without losing cached template names", async () => {
  saved.permissions = ["read"];
  saved.document_template = { mode: "selected", template_id: "report" };
  const { queryClient } = show();
  await screen.findByText("Dokumentmall: Rapport");
  api.GET.mockResolvedValueOnce({
    data: undefined,
    error: { message: "Refresh unavailable" },
    response: new Response(null, { status: 503 })
  });
  await act(async () => {
    await queryClient.invalidateQueries({ queryKey: ["document-templates"] });
  });
  const retry = await screen.findByRole("button", { name: /Försök igen:/ });
  expect(screen.getByText("Dokumentmall: Rapport")).toBeTruthy();
  retry.focus();
  fireEvent.click(retry);
  await waitFor(() => expect(screen.queryByRole("button", { name: /Försök igen:/ })).toBeNull());
  await waitFor(() =>
    expect(document.activeElement).toBe(screen.getByText("Dokumentmall: Rapport"))
  );
  expect(api.POST).not.toHaveBeenCalled();
});

function showCapabilities() {
  const queryClient = testQueryClient();
  queryClient.setQueryData(assistantQueryOptions(browserApi, saved.id).queryKey, saved);
  return renderInApp(
    <SaveStatusProvider>
      <header>
        <SaveStatusIndicator />
      </header>
      <Harness capabilities />
    </SaveStatusProvider>,
    { queryClient }
  );
}

it("does not queue a template write behind disabling file creation or strand page status", async () => {
  let finish!: () => void;
  api.POST.mockImplementationOnce(
    () =>
      new Promise<ReturnType<typeof ok>>((resolve) => {
        finish = () => {
          saved = { ...saved, enabled_capabilities: [] };
          resolve(ok(saved));
        };
      })
  );
  api.POST.mockResolvedValueOnce({
    data: undefined,
    error: { message: "Queued template failure" },
    response: new Response(null, { status: 503 })
  });
  showCapabilities();
  fireEvent.click(screen.getByRole("button", { name: "Ändra dokumentmall" }));
  await screen.findByText("Kommunens mall");
  fireEvent.click(screen.getByRole("switch", { name: "Skapa fil" }));
  await waitFor(() => expect(api.POST).toHaveBeenCalledTimes(1));
  fireEvent.click(screen.getByRole("radio", { name: /Organisationens standard/ }));
  await act(async () => finish());
  await waitFor(() =>
    expect(screen.queryByRole("button", { name: "Ändra dokumentmall" })).toBeNull()
  );
  await waitFor(() =>
    expect(within(screen.getByRole("banner")).getByText(messages.all_changes_saved)).toBeTruthy()
  );
  expect(api.POST).toHaveBeenCalledTimes(1);
  const beforeUnload = new Event("beforeunload", { cancelable: true });
  window.dispatchEvent(beforeUnload);
  expect(beforeUnload.defaultPrevented).toBe(false);
  expect(document.getElementById("assistant-document-template")).toBeNull();
});

it("blocks named choices and a failed-choice retry while the actual capability section saves", async () => {
  api.POST.mockResolvedValueOnce({
    data: undefined,
    error: { message: "Cannot save template" },
    response: new Response(null, { status: 503 })
  });
  let finish!: () => void;
  api.POST.mockImplementationOnce(
    () =>
      new Promise<ReturnType<typeof ok>>((resolve) => {
        finish = () => {
          saved = { ...saved, enabled_capabilities: [] };
          resolve(ok(saved));
        };
      })
  );
  showCapabilities();
  fireEvent.click(screen.getByRole("button", { name: "Ändra dokumentmall" }));
  await screen.findByText("Kommunens mall");
  fireEvent.click(screen.getByRole("radio", { name: "En annan mall" }));
  const retry = await screen.findByRole("button", {
    name: "Försök igen: Kunde inte spara ändringarna"
  });
  fireEvent.click(screen.getByRole("switch", { name: "Skapa fil" }));
  await waitFor(() => expect(api.POST).toHaveBeenCalledTimes(2));
  try {
    expect(
      screen.getByRole("radio", { name: "Eneos inbyggda mall" }).getAttribute("aria-disabled")
    ).toBe("true");
    expect(
      screen.getByRole("combobox", { name: "En annan mall" }).getAttribute("aria-disabled")
    ).toBe("true");
    expect(retry.getAttribute("aria-busy")).toBe("true");
    fireEvent.click(retry);
    fireEvent.click(screen.getByRole("radio", { name: "Eneos inbyggda mall" }));
  } finally {
    await act(async () => finish());
  }
  await waitFor(() =>
    expect(within(screen.getByRole("banner")).getByText(messages.all_changes_saved)).toBeTruthy()
  );
  expect(api.POST).toHaveBeenCalledTimes(2);
});
