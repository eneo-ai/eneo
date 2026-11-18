// @vitest-environment jsdom
import { cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { ToolCallRecord, ToolPart } from "@/features/chat/side-panel/message-tool-calls";
import { expectNoAxeViolations } from "@/test/axe";
import { renderInApp, testQueryClient } from "@/test/render";
import { assistantHelperCardFor } from "./assistant-helper-cards";
import type { Assistant } from "./use-assistant";

const api = vi.hoisted(() => ({ GET: vi.fn(), POST: vi.fn() }));
const announce = vi.hoisted(() => vi.fn());
const toast = vi.hoisted(() => ({ error: vi.fn(), success: vi.fn(), info: vi.fn() }));

vi.mock("@/lib/api/browser", () => ({ browserApi: api }));
vi.mock("@/lib/toast", () => ({ toast }));
vi.mock("@astryxdesign/core/hooks", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@astryxdesign/core/hooks")>()),
  useAnnounce: () => announce
}));
vi.mock("@/features/spaces/use-space", async () => {
  const { useSpaceFromQuery } = await import("@/features/spaces/testing/space-query");
  const { makeSpace } = await import("@/features/spaces/testing/space-fixture");
  return { useSpace: () => useSpaceFromQuery(() => makeSpace()) };
});

const ID = "assistant-1";
const HAIKU = { id: "model-1", name: "claude-haiku" };
const OPUS = { id: "model-2", name: "claude-opus" };

function makeAssistant(overrides: Record<string, unknown> = {}): Assistant {
  return {
    id: ID,
    name: "Skolhjälpen",
    description: "Svarar på frågor om skolval.",
    prompt: { text: "Svara kort och vänligt." },
    completion_model: HAIKU,
    completion_model_kwargs: { temperature: 0.7 },
    knowledge_mode: "tool",
    inline_file_text: false,
    permissions: ["read", "edit"],
    effective_config: null,
    ...overrides
  } as unknown as Assistant;
}

function toolCall(
  toolName: string,
  structuredContent: Record<string, unknown> | null,
  { serverName = "assistant", isInternal = true } = {}
): ToolCallRecord {
  return {
    toolCallId: `call-${toolName}`,
    toolName,
    state: "output-available",
    input: {},
    serverName,
    title: null,
    purpose: null,
    isInternal,
    isBundled: false,
    appView: null,
    approved: null,
    resultStatus: "succeeded",
    generatedFileIds: [],
    structuredContent,
    part: {} as ToolPart
  };
}

const PROPOSAL_UPDATE = {
  name: "Skolvalshjälpen",
  completion_model: { id: OPUS.id },
  completion_model_kwargs: { temperature: 0.2 },
  knowledge_mode: "inject",
  inline_file_text: true
};

/** A proposal of five settings, as `propose_changes` returns it. */
const proposal = (overrides: Record<string, unknown> = {}) =>
  toolCall("propose_changes", {
    target_id: ID,
    proposal: {
      changes: [
        { field: "name", before: "Skolhjälpen", after: "Skolvalshjälpen" },
        { field: "completion_model", before: HAIKU, after: OPUS },
        { field: "completion_model_kwargs.temperature", before: 0.7, after: 0.2 },
        { field: "knowledge_mode", before: "tool", after: "inject" },
        { field: "inline_file_text", before: false, after: true }
      ],
      update: PROPOSAL_UPDATE,
      ...overrides
    }
  });

/** A change of the name that `update_assistant` made, with its undo. */
const nameChange = () =>
  toolCall("update_assistant", {
    target_id: ID,
    changes: [{ field: "name", before: "Skolhjälpen", after: "Skolvalshjälpen" }],
    undo: { name: "Skolhjälpen" }
  });

const ok = (data: unknown) => ({ data, response: new Response(null, { status: 200 }) });

function renderCard(call: ToolCallRecord, assistant: Assistant = makeAssistant()) {
  const queryClient = testQueryClient();
  queryClient.setQueryData(["assistants", ID], assistant);
  return renderInApp(<>{assistantHelperCardFor(call, ID)}</>, { queryClient });
}

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe("The helper's proposal card", () => {
  it("names each setting as the editor does, before and after, and says it is not saved", () => {
    renderCard(proposal());

    const card = screen.getByRole("region", { name: "Förslag på 5 ändringar" });
    expect(within(card).getByText("Inte sparat")).toBeTruthy();
    const rows = within(card)
      .getAllByRole("listitem")
      .map((row) => [...row.querySelectorAll("p, dd")].map((part) => part.textContent));
    expect(rows).toEqual([
      ["Namn", "Skolhjälpen", "Skolvalshjälpen"],
      ["Chattmodell", "claude-haiku", "claude-opus"],
      ["Temperatur", "0,7", "0,2"],
      ["Sökning i kunskapskällor", "Vid behov", "Inför varje svar"],
      ["Dokument från användare i chatten", "Öppna vid behov", "Läs in direkt"]
    ]);
  });

  it("saves exactly the proposal's request with Använd, and then shows it as used", async () => {
    api.POST.mockResolvedValue(
      ok(
        makeAssistant({
          name: "Skolvalshjälpen",
          completion_model: OPUS,
          completion_model_kwargs: { temperature: 0.2 },
          knowledge_mode: "inject",
          inline_file_text: true
        })
      )
    );
    renderCard(proposal());
    const apply = screen.getByRole("button", { name: "Använd" });
    apply.focus();

    fireEvent.click(apply);

    await waitFor(() => expect(screen.getByText("Använt")).toBeTruthy());
    // The button went with the save: focus is on what the card says now, not lost.
    await waitFor(() => expect(document.activeElement?.textContent).toBe("Använt"));
    expect(api.POST).toHaveBeenCalledTimes(1);
    expect(api.POST).toHaveBeenCalledWith("/api/v1/assistants/{id}/", {
      params: { path: { id: ID } },
      body: PROPOSAL_UPDATE
    });
    expect(announce).toHaveBeenCalledWith("Ändringen är sparad.");
    expect(screen.queryByRole("button", { name: "Använd" })).toBeNull();
    expect(screen.queryByText("Inte sparat")).toBeNull();
  });

  it("shows a proposal the assistant already has as used, after a reload, with nothing to press", () => {
    renderCard(
      proposal(),
      makeAssistant({
        name: "Skolvalshjälpen",
        completion_model: OPUS,
        completion_model_kwargs: { temperature: 0.2 },
        knowledge_mode: "inject",
        inline_file_text: true
      })
    );

    expect(screen.getByText("Använt")).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Använd" })).toBeNull();
  });

  it("offers it again once a setting it changed has been changed after it was used", () => {
    renderCard(
      proposal(),
      makeAssistant({
        name: "Skolvalshjälpen",
        completion_model: OPUS,
        completion_model_kwargs: { temperature: 0.4 },
        knowledge_mode: "inject",
        inline_file_text: true
      })
    );

    expect(screen.getByRole("button", { name: "Använd" })).toBeTruthy();
  });

  it("says a failed save at the card and in a toast, and stays usable", async () => {
    api.POST.mockResolvedValue({
      error: { message: "The instructions and files no longer fit the model." },
      response: new Response(null, { status: 400 })
    });
    renderCard(proposal());

    fireEvent.click(screen.getByRole("button", { name: "Använd" }));

    expect(
      await screen.findByText("The instructions and files no longer fit the model.")
    ).toBeTruthy();
    expect(toast.error).toHaveBeenCalledWith(
      "Ändringen sparades inte",
      expect.objectContaining({
        description: expect.stringContaining("The instructions and files no longer fit the model.")
      })
    );
    expect(announce).not.toHaveBeenCalled();
    const button = screen.getByRole("button", { name: "Använd" });
    await waitFor(() => expect(button.getAttribute("aria-disabled")).not.toBe("true"));
    fireEvent.click(button);
    await waitFor(() => expect(api.POST).toHaveBeenCalledTimes(2));
  });

  it("offers nothing to someone who may not edit the assistant", () => {
    renderCard(proposal(), makeAssistant({ permissions: ["read"] }));

    expect(screen.getByRole("region", { name: "Förslag på 5 ändringar" })).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Använd" })).toBeNull();
  });

  it("disables Använd with the reason where a policy sets the instructions", () => {
    renderCard(
      toolCall("propose_changes", {
        target_id: ID,
        proposal: {
          changes: [{ field: "prompt", before: "Svara kort.", after: "Svara utförligt." }],
          update: { prompt: { text: "Svara utförligt.", description: "Längre svar" } }
        }
      }),
      makeAssistant({ effective_config: { prompt_locked: true } })
    );

    const button = screen.getByRole("button", { name: "Använd" });
    expect(button.getAttribute("aria-disabled")).toBe("true");
    const reason = document.getElementById(button.getAttribute("aria-describedby")!.split(" ")[0]!);
    expect(reason?.textContent).toBe(
      "Prompt styrs av organisationens policy och kan inte ändras här."
    );
    fireEvent.click(button);
    expect(api.POST).not.toHaveBeenCalled();
  });

  it("disables Använd with the reason for a model the policy locks or the editor does not offer", () => {
    const opusOnly = (model: { id: string; name: string }) =>
      toolCall("propose_changes", {
        target_id: ID,
        proposal: {
          changes: [{ field: "completion_model", before: HAIKU, after: model }],
          update: { completion_model: { id: model.id } }
        }
      });
    renderCard(
      opusOnly(OPUS),
      makeAssistant({
        effective_config: {
          models_enforced: true,
          locked_model: HAIKU,
          available_models: [HAIKU, OPUS]
        }
      })
    );
    expect(
      screen.getByText("Chattmodell styrs av organisationens policy och kan inte ändras här.")
    ).toBeTruthy();
    cleanup();

    renderCard(opusOnly({ id: "model-9", name: "retired-model" }));
    const button = screen.getByRole("button", { name: "Använd" });
    expect(button.getAttribute("aria-disabled")).toBe("true");
    expect(screen.getByText("retired-model kan inte väljas för den här assistenten.")).toBeTruthy();
  });

  it("shows new instructions in a block of their own, with the earlier text and Kopiera", async () => {
    const writeText = vi.fn(() => Promise.resolve());
    Object.defineProperty(navigator, "clipboard", { value: { writeText }, configurable: true });
    const text = Array.from({ length: 8 }, (_, line) => `Regel ${line + 1}.`).join("\n");
    renderCard(
      toolCall("propose_changes", {
        target_id: ID,
        proposal: {
          changes: [{ field: "prompt", before: "Svara kort och vänligt.", after: text }],
          update: { prompt: { text, description: "Regler" } }
        }
      })
    );

    expect(screen.getByText("Prompt")).toBeTruthy();
    expect(screen.getByRole("button", { name: "Visa hela" })).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Tidigare text" }));
    expect(await screen.findByText("Svara kort och vänligt.")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Kopiera" }));
    await waitFor(() => expect(writeText).toHaveBeenCalledWith(text));
  });

  it("says instructions too long to show are not shown, and still applies and copies them", async () => {
    const writeText = vi.fn(() => Promise.resolve());
    Object.defineProperty(navigator, "clipboard", { value: { writeText }, configurable: true });
    const update = { prompt: { text: "Mycket lång text", description: "Lång" } };
    api.POST.mockResolvedValue(ok(makeAssistant({ prompt: { text: "Mycket lång text" } })));
    renderCard(
      toolCall("propose_changes", {
        target_id: ID,
        proposal: {
          changes: [{ field: "prompt", before: null, after: null, too_long: true }],
          update
        }
      })
    );

    expect(screen.getByText("Texten är för lång för att visas här.")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Kopiera" }));
    await waitFor(() => expect(writeText).toHaveBeenCalledWith("Mycket lång text"));
    fireEvent.click(screen.getByRole("button", { name: "Använd" }));
    await waitFor(() => expect(screen.getByText("Använt")).toBeTruthy());
    expect(api.POST).toHaveBeenCalledWith("/api/v1/assistants/{id}/", {
      params: { path: { id: ID } },
      body: update
    });
  });
});

describe("The helper's change card", () => {
  it("says the helper made the change, and undoes exactly it with Ångra", async () => {
    api.POST.mockResolvedValue(ok(makeAssistant({ name: "Skolhjälpen" })));
    renderCard(nameChange(), makeAssistant({ name: "Skolvalshjälpen" }));

    const card = screen.getByRole("region", { name: "Hjälpassistenten ändrade en inställning" });
    expect(within(card).getByText("Skolhjälpen")).toBeTruthy();
    expect(within(card).getByText("Skolvalshjälpen")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Ångra" }));

    await waitFor(() => expect(screen.getByText("Ångrat")).toBeTruthy());
    expect(api.POST).toHaveBeenCalledWith("/api/v1/assistants/{id}/", {
      params: { path: { id: ID } },
      body: { name: "Skolhjälpen" }
    });
    expect(announce).toHaveBeenCalledWith("Ändringen är ångrad.");
    expect(screen.queryByRole("button", { name: "Ångra" })).toBeNull();
  });

  it("withholds Ångra and says so once the setting has been changed since", () => {
    renderCard(nameChange(), makeAssistant({ name: "Skolvalsstöd" }));

    expect(screen.getByText("Inställningen har ändrats sedan dess.")).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Ångra" })).toBeNull();
  });

  it("shows a change undone before a reload as undone", () => {
    renderCard(nameChange(), makeAssistant({ name: "Skolhjälpen" }));

    expect(screen.getByText("Ångrat")).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Ångra" })).toBeNull();
  });

  it("offers no Ångra to someone who may not edit the assistant", () => {
    renderCard(nameChange(), makeAssistant({ name: "Skolvalshjälpen", permissions: ["read"] }));

    expect(screen.queryByRole("button", { name: "Ångra" })).toBeNull();
  });

  it("disables Ångra with the reason where the earlier model is no longer offered", () => {
    renderCard(
      toolCall("update_assistant", {
        target_id: ID,
        changes: [
          {
            field: "completion_model",
            before: { id: "model-9", name: "retired-model" },
            after: OPUS
          }
        ],
        undo: { completion_model: { id: "model-9" } }
      }),
      makeAssistant({ completion_model: OPUS })
    );

    expect(screen.getByRole("button", { name: "Ångra" }).getAttribute("aria-disabled")).toBe(
      "true"
    );
    expect(screen.getByText("retired-model kan inte väljas för den här assistenten.")).toBeTruthy();
  });

  it("undoes instructions too long to show while they have not been put back", () => {
    renderCard(
      toolCall("update_assistant", {
        target_id: ID,
        changes: [{ field: "prompt", before: null, after: null, too_long: true }],
        undo: { prompt: { text: "Svara kort och vänligt.", description: "Ångrad" } }
      }),
      makeAssistant({ prompt: { text: "Mycket lång text" } })
    );

    expect(screen.getByText("Texten är för lång för att visas här.")).toBeTruthy();
    expect(screen.getByRole("button", { name: "Ångra" })).toBeTruthy();
  });
});

describe("The helper's cards", () => {
  it("draw nothing for another server's call, a call about another assistant or one with nothing to show", () => {
    const calls = [
      proposal(),
      nameChange(),
      toolCall("update_assistant", nameChange().structuredContent, { serverName: "flows" }),
      toolCall("update_assistant", nameChange().structuredContent, { isInternal: false }),
      toolCall("update_assistant", { ...nameChange().structuredContent, target_id: "other" }),
      toolCall("propose_changes", { target_id: ID }),
      toolCall("update_assistant", { target_id: ID, changes: [], undo: null }),
      toolCall("read_assistant", { target_id: ID }),
      toolCall("update_assistant", null)
    ];
    expect(calls.map((call) => assistantHelperCardFor(call, ID) !== null)).toEqual([
      true,
      true,
      false,
      false,
      false,
      false,
      false,
      false,
      false
    ]);
  });

  it("have no axe violations", async () => {
    const { container } = renderCard(proposal());
    await expectNoAxeViolations(container);
    cleanup();
    const change = renderCard(nameChange(), makeAssistant({ name: "Skolvalshjälpen" }));
    await expectNoAxeViolations(change.container);
  });
});
