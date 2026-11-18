// @vitest-environment jsdom
import { cleanup, fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import messages from "@/lib/i18n/messages/sv.json";
import { renderInApp } from "@/test/render";
// The flow is the helper's one target so far: its endpoints stand in for any target's.
import { flowHelperApi } from "@/features/flows/flows-api";
import type { HelperAdapter, HelperTexts } from "./helper-adapter";
import { HelperPanel } from "./helper-panel";

const api = vi.hoisted(() => ({ GET: vi.fn(), POST: vi.fn(), PATCH: vi.fn() }));
const announce = vi.hoisted(() => vi.fn());

vi.mock("@/lib/api/browser", () => ({ browserApi: api }));
vi.mock("@/lib/navigation", () => import("@/test/navigation"));
vi.mock("@astryxdesign/core/hooks", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@astryxdesign/core/hooks")>()),
  useAnnounce: () => announce
}));
vi.mock("@/features/spaces/use-space", async () => {
  const { useSpaceFromQuery } = await import("@/features/spaces/testing/space-query");
  const { makeSpace } = await import("@/features/spaces/testing/space-fixture");
  // A personal space: its own chat lists other conversations, the helper must not.
  return { useSpace: () => useSpaceFromQuery(() => makeSpace({ overrides: { personal: true } })) };
});
// The conversation is the chat feature's; the panel decides its welcome, footer and
// placeholder, and hands on what the conversation reports.
vi.mock("@/features/chat/chat-view", () => ({
  ChatView: ({
    footerActions,
    placeholder,
    composerLabel,
    partner,
    onToolCallFinished,
    onAnswerFinished
  }: {
    footerActions?: unknown;
    placeholder?: string;
    composerLabel?: string;
    partner?: { name?: string; description?: string; personalSpace?: boolean };
    onToolCallFinished?: (call: { serverName: string; isInternal: boolean }) => void;
    onAnswerFinished?: () => void;
  }) => (
    <div>
      <p>partner: {partner?.name}</p>
      <p>{partner?.description}</p>
      {partner?.personalSpace ? <p>personal lists</p> : null}
      {footerActions as React.ReactNode}
      <p>{placeholder}</p>
      <p>composer: {composerLabel ?? "partner"}</p>
      <button
        type="button"
        onClick={() => onToolCallFinished?.({ serverName: "target", isInternal: true })}
      >
        Verktyg klart
      </button>
      <button type="button" onClick={() => onAnswerFinished?.()}>
        Svar klart
      </button>
    </div>
  )
}));

/** A target's words, none of them the flow's. */
const TEXTS: HelperTexts = {
  heading: "Hjälp med målet",
  partnerName: "Målhjälpen",
  partnerDescription: { ask: "Jag läser målet.", edit: "Jag ändrar målet." },
  placeholder: { ask: "Fråga om målet…", edit: "Beskriv ändringen av målet…" },
  composerLabelEdit: "Beskriv ändringen av målet",
  modeDescription: { ask: "Läser målet.", edit: "Ändrar målet direkt." },
  editingOn: "Nu kan chatten ändra målet.",
  editingOff: "Nu kan chatten bara läsa målet.",
  askAfterPause: "Fråga igen efter en paus.",
  noAccess: "Du får inte ändra målet.",
  newConversationDescription: "Målet påverkas inte."
};

function adapter(overrides: Partial<HelperAdapter> = {}): HelperAdapter {
  return {
    api: flowHelperApi("flow-1"),
    unavailable: null,
    texts: TEXTS,
    onRefused: () => {},
    ...overrides
  };
}

function renderPanel(target: HelperAdapter = adapter()) {
  return renderInApp(<HelperPanel adapter={target} />);
}

const ok = (data: unknown) => ({ data, response: new Response(null, { status: 200 }) });
const CHAT = { flow_id: "flow-1", assistant_id: "assistant-chat", session_id: "session-1" };

function refuseChat(body: Record<string, unknown>) {
  api.POST.mockResolvedValue({ error: body, response: new Response(null, { status: 400 }) });
}

/** The chat opens, with its assistant and an empty conversation, in the given mode. */
function openChat(editing: boolean) {
  api.POST.mockResolvedValue(ok({ ...CHAT, editing }));
  api.PATCH.mockResolvedValue(ok({ ...CHAT, editing: !editing }));
  api.GET.mockImplementation(async (path: string) =>
    path === "/api/v1/assistants/{id}/"
      ? ok({ id: "assistant-chat", name: "Medborgarbrev", mcp_servers: [] })
      : ok({ id: "session-1", name: "", messages: [] })
  );
}

/** Picks Redigera in the composer's footer. */
async function pickEdit() {
  fireEvent.click(await screen.findByRole("button", { name: "Läge: Fråga" }));
  fireEvent.click(await screen.findByRole("menuitemradio", { name: /Redigera/ }));
}

/** The status of the banner around the given text. */
async function bannerStatus(text: string) {
  const description = await screen.findByText(text);
  return description.closest(".astryx-banner")?.getAttribute("data-status");
}

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe("HelperPanel when the chat cannot open", () => {
  it("says in Swedish who declares a model's limits, as a warning", async () => {
    refuseChat({
      message: "Unknown model capacity: max_input_tokens",
      code: "unknown_model_capacity",
      eneo_error_code: 9074
    });
    renderPanel();

    expect(await bannerStatus(messages.flows_chat_model_capacity_unknown)).toBe("warning");
    expect(screen.getByText(messages.flows_chat_unavailable)).toBeTruthy();
    expect(screen.queryByText(/Unknown model capacity/)).toBeNull();
  });

  it("never shows the core's English for a refusal it has no text for", async () => {
    refuseChat({ message: "Something internal went sideways.", code: "brand_new_refusal" });
    renderPanel();

    expect(await screen.findByText(messages.request_failed)).toBeTruthy();
    expect(screen.queryByText(/sideways/)).toBeNull();
  });

  it("uses the target's words for a refusal the target has them for", async () => {
    refuseChat({ message: "No model.", code: "target_no_model", eneo_error_code: 9007 });
    renderPanel(
      adapter({ refusalText: (reason) => (reason === "target_no_model" ? "Ingen modell." : null) })
    );

    expect(await bannerStatus("Ingen modell.")).toBe("info");
    expect(screen.queryByText("No model.")).toBeNull();
  });

  it("does not ask for the chat of someone the target says may not use it, and says why", async () => {
    renderPanel(adapter({ unavailable: "Ytan har ingen modell för chatten." }));

    expect(await bannerStatus("Ytan har ingen modell för chatten.")).toBe("info");
    expect(screen.getByText(messages.flows_chat_unavailable)).toBeTruthy();
    expect(api.POST).not.toHaveBeenCalled();
  });

  it("says the server's refusal for want of access in the target's words", async () => {
    api.POST.mockResolvedValue({
      error: { message: "Forbidden.", eneo_error_code: 9006 },
      response: new Response(null, { status: 403 })
    });
    renderPanel();

    expect(await bannerStatus(TEXTS.noAccess)).toBe("info");
    expect(screen.queryByText("Forbidden.")).toBeNull();
  });
});

describe("HelperPanel's close", () => {
  it("has no close where the page keeps the panel on screen", async () => {
    openChat(false);
    renderPanel();

    expect(await screen.findByRole("button", { name: "Läge: Fråga" })).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Stäng panelen" })).toBeNull();
  });

  it("closes from the end of the title row, also while the chat cannot open", async () => {
    const onClose = vi.fn();
    renderInApp(
      <HelperPanel
        adapter={adapter({ unavailable: "Inte här." })}
        close={{ label: "Stäng panelen", onClose }}
      />
    );

    const button = await screen.findByRole("button", { name: "Stäng panelen" });
    const heading = screen.getByRole("heading", { level: 2, name: TEXTS.heading });
    expect(heading.compareDocumentPosition(button) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(await bannerStatus("Inte här.")).toBe("info");
    fireEvent.click(button);
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("is a way back before the heading where the panel fills the screen", async () => {
    openChat(false);
    const onClose = vi.fn();
    renderInApp(
      <HelperPanel adapter={adapter()} close={{ label: "Tillbaka", onClose, asBack: true }} />
    );

    const back = await screen.findByRole("button", { name: "Tillbaka" });
    const heading = screen.getByRole("heading", { level: 2, name: TEXTS.heading });
    expect(back.compareDocumentPosition(heading) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    fireEvent.click(back);
    expect(onClose).toHaveBeenCalledTimes(1);
  });
});

describe("HelperPanel's mode", () => {
  it("offers Redigera, in the target's words, while the target is not locked", async () => {
    openChat(false);
    renderPanel();

    expect(await screen.findByRole("heading", { level: 2, name: TEXTS.heading })).toBeTruthy();
    fireEvent.click(await screen.findByRole("button", { name: "Läge: Fråga" }));
    const edit = await screen.findByRole("menuitemradio", { name: /Redigera/ });
    expect(edit.getAttribute("aria-disabled")).not.toBe("true");
    expect(edit.textContent).toContain(TEXTS.modeDescription.edit);
    expect(screen.getByText(`partner: ${TEXTS.partnerName}`)).toBeTruthy();
    expect(screen.getByText(TEXTS.partnerDescription.ask)).toBeTruthy();
    expect(screen.getByText(TEXTS.placeholder.ask)).toBeTruthy();
  });

  it("names the composer and the welcome by Redigera once it is on", async () => {
    openChat(false);
    renderPanel();
    await pickEdit();

    expect(await screen.findByRole("button", { name: "Läge: Redigera" })).toBeTruthy();
    await waitFor(() => expect(announce).toHaveBeenCalledWith(TEXTS.editingOn));
    expect(screen.getByText(TEXTS.placeholder.edit)).toBeTruthy();
    expect(screen.getByText(`composer: ${TEXTS.composerLabelEdit}`)).toBeTruthy();
    expect(screen.getByText(TEXTS.partnerDescription.edit)).toBeTruthy();
  });

  it("fences a mode change on the revision the target has on screen", async () => {
    openChat(false);
    renderPanel(adapter({ revision: () => 7 }));
    await pickEdit();

    await waitFor(() =>
      expect(api.PATCH).toHaveBeenCalledWith("/api/v1/flows/{id}/authoring-chat/{session_id}/", {
        params: { path: { id: "flow-1", session_id: "session-1" } },
        body: { editing: true, expected_revision: 7 }
      })
    );
  });

  it("sends no revision for a target that has none", async () => {
    openChat(false);
    renderPanel();
    await pickEdit();

    await waitFor(() => expect(api.PATCH).toHaveBeenCalledTimes(1));
    expect(api.PATCH).toHaveBeenCalledWith("/api/v1/flows/{id}/authoring-chat/{session_id}/", {
      params: { path: { id: "flow-1", session_id: "session-1" } },
      body: { editing: true }
    });
  });

  it("hands a refused mode change to the page", async () => {
    openChat(false);
    api.PATCH.mockResolvedValue({
      error: { message: "Stale.", code: "stale", eneo_error_code: 9007 },
      response: new Response(null, { status: 409 })
    });
    const onRefused = vi.fn();
    renderPanel(adapter({ onRefused }));
    await pickEdit();

    await waitFor(() => expect(onRefused).toHaveBeenCalledTimes(1));
    expect(onRefused.mock.calls[0]![1]).toBe(messages.flows_notice_mode_not_changed);
    expect(await screen.findByRole("button", { name: "Läge: Fråga" })).toBeTruthy();
  });
});

describe("HelperPanel's conversation", () => {
  it("hands finished tool calls and answers to the page, and reads the chat again", async () => {
    openChat(false);
    const onToolCallFinished = vi.fn();
    const onAnswerFinished = vi.fn();
    renderPanel(adapter({ onToolCallFinished, onAnswerFinished }));

    fireEvent.click(await screen.findByRole("button", { name: "Verktyg klart" }));
    expect(onToolCallFinished).toHaveBeenCalledWith({ serverName: "target", isInternal: true });
    expect(api.POST).toHaveBeenCalledTimes(1);

    fireEvent.click(screen.getByRole("button", { name: "Svar klart" }));
    expect(onAnswerFinished).toHaveBeenCalledTimes(1);
    // The turn's start may have left edit mode after a pause.
    await waitFor(() => expect(api.POST).toHaveBeenCalledTimes(2));
  });

  it("tells the page the composer is gone when the conversation leaves", async () => {
    openChat(false);
    const onComposer = vi.fn();
    const { unmount } = renderPanel(
      adapter({ references: { remarkPlugins: [], components: {}, onComposer } })
    );
    expect(await screen.findByRole("button", { name: "Läge: Fråga" })).toBeTruthy();
    expect(onComposer).not.toHaveBeenCalled();

    unmount();
    expect(onComposer).toHaveBeenCalledWith(null);
  });

  it("puts the target's actions in the title row, beside the chat's own", async () => {
    openChat(false);
    renderPanel(adapter({ headerActions: <button type="button">Målets åtgärd</button> }));

    expect(await screen.findByRole("button", { name: "Målets åtgärd" })).toBeTruthy();
    expect(screen.getByRole("button", { name: messages.flows_chat_new_conversation })).toBeTruthy();
    expect(screen.getByRole("button", { name: messages.flows_chat_settings })).toBeTruthy();
  });

  it("puts the target's controls in the composer's footer, before the mode picker", async () => {
    openChat(false);
    renderPanel(adapter({ footerActions: <button type="button">Målets kontroll</button> }));

    const mode = await screen.findByRole("button", { name: "Läge: Fråga" });
    const control = screen.getByRole("button", { name: "Målets kontroll" });
    expect(control.compareDocumentPosition(mode) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });
});
