// @vitest-environment jsdom
import { act, cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import messages from "@/lib/i18n/messages/sv.json";
import { renderInApp, testQueryClient } from "@/test/render";
// The flow is the helper's one target so far: its endpoints stand in for any target's.
import { flowHelperApi, flowKeys } from "@/features/flows/flows-api";
import type { HelperAdapter, HelperModes, HelperTexts } from "./helper-adapter";
import { HelperPanel } from "./helper-panel";

const api = vi.hoisted(() => ({ GET: vi.fn(), POST: vi.fn(), PATCH: vi.fn() }));
const announce = vi.hoisted(() => vi.fn());
/**
 * What the conversation's own send decided: true where the page let the
 * message go. A message with files waits for them with the callbacks of the
 * render it was sent from.
 */
const conversation = vi.hoisted(() => ({
  sent: [] as boolean[],
  waiting: undefined as (() => Promise<boolean>) | undefined,
  /** The composer the conversation reports through the page's references, if any. */
  composer: null as { insertText: (text: string) => void; insertToken: () => void } | null
}));

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
vi.mock("@/features/chat/chat-view", async () => {
  const { useEffect } = await import("react");
  return { ChatView: MockChatView };

  function MockChatView({
    footerActions,
    placeholder,
    composerLabel,
    partner,
    onToolCallFinished,
    onAnswerFinished,
    beforeSend,
    references
  }: {
    footerActions?: unknown;
    placeholder?: string;
    composerLabel?: string;
    partner?: { name?: string; description?: string; personalSpace?: boolean };
    onToolCallFinished?: (call: { serverName: string; isInternal: boolean }) => void;
    onAnswerFinished?: () => void;
    beforeSend?: () => Promise<boolean>;
    references?: { onComposer?: (input: unknown) => void };
  }) {
    const onComposer = references?.onComposer;
    useEffect(() => {
      if (conversation.composer) onComposer?.(conversation.composer);
    }, [onComposer]);
    return (
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
        <button
          type="button"
          onClick={() => void beforeSend?.().then((go) => conversation.sent.push(go))}
        >
          Skicka
        </button>
        <button type="button" onClick={() => (conversation.waiting = beforeSend)}>
          Skicka med filer
        </button>
        <button
          type="button"
          onClick={() => void conversation.waiting?.().then((go) => conversation.sent.push(go))}
        >
          Filerna uppladdade
        </button>
        <p>{beforeSend ? "asks before sending" : "sends at once"}</p>
        <textarea aria-label="Meddelande" />
      </div>
    );
  }
});

/** A target's words, none of them the flow's. */
const TEXTS: HelperTexts = {
  heading: "Hjälp med målet",
  partnerName: "Målhjälpen",
  partnerDescription: "Jag läser målet.",
  placeholder: "Fråga om målet…",
  noAccess: "Du får inte ändra målet.",
  newConversationDescription: "Målet påverkas inte."
};

/** The target's two modes, in its words. */
const MODES: HelperModes = {
  description: { ask: "Läser målet.", edit: "Ändrar målet direkt." },
  edit: {
    partnerDescription: "Jag ändrar målet.",
    placeholder: "Beskriv ändringen av målet…",
    composerLabel: "Beskriv ändringen av målet"
  },
  editingOn: "Nu kan chatten ändra målet.",
  editingOff: "Nu kan chatten bara läsa målet.",
  askAfterPause: "Fråga igen efter en paus."
};

/** A target with modes, unless the overrides say otherwise. */
function adapter(overrides: Partial<HelperAdapter> = {}): HelperAdapter {
  return {
    api: flowHelperApi("flow-1"),
    unavailable: null,
    texts: TEXTS,
    modes: MODES,
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
  conversation.sent = [];
  conversation.waiting = undefined;
  conversation.composer = null;
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
    expect(edit.textContent).toContain(MODES.description.edit);
    expect(screen.getByText(`partner: ${TEXTS.partnerName}`)).toBeTruthy();
    expect(screen.getByText(TEXTS.partnerDescription)).toBeTruthy();
    expect(screen.getByText(TEXTS.placeholder)).toBeTruthy();
  });

  it("names the composer and the welcome by Redigera once it is on", async () => {
    openChat(false);
    renderPanel();
    await pickEdit();

    expect(await screen.findByRole("button", { name: "Läge: Redigera" })).toBeTruthy();
    await waitFor(() => expect(announce).toHaveBeenCalledWith(MODES.editingOn));
    expect(screen.getByText(MODES.edit.placeholder)).toBeTruthy();
    expect(screen.getByText(`composer: ${MODES.edit.composerLabel}`)).toBeTruthy();
    expect(screen.getByText(MODES.edit.partnerDescription)).toBeTruthy();
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

  it("says so when a read finds the server left Redigera after a pause", async () => {
    openChat(true);
    renderPanel();
    expect(await screen.findByRole("button", { name: "Läge: Redigera" })).toBeTruthy();

    api.POST.mockResolvedValue(ok({ ...CHAT, editing: false }));
    fireEvent.click(screen.getByRole("button", { name: "Svar klart" }));

    await waitFor(() => expect(announce).toHaveBeenCalledWith(MODES.askAfterPause));
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

describe("HelperPanel on a target without modes", () => {
  const oneMode = (overrides: Partial<HelperAdapter> = {}) =>
    adapter({ modes: null, ...overrides });

  it("shows no mode picker and one set of words, whatever the chat says of its mode", async () => {
    openChat(true);
    renderPanel(oneMode({ footerActions: <button type="button">Målets kontroll</button> }));

    expect(await screen.findByRole("button", { name: "Målets kontroll" })).toBeTruthy();
    expect(screen.queryByRole("button", { name: /^Läge:/ })).toBeNull();
    expect(screen.getByText(TEXTS.partnerDescription)).toBeTruthy();
    expect(screen.getByText(TEXTS.placeholder)).toBeTruthy();
    expect(screen.getByText("composer: partner")).toBeTruthy();
    expect(screen.queryByText(MODES.edit.partnerDescription)).toBeNull();
  });

  it("never announces a mode, whatever a read of the chat says of it", async () => {
    openChat(true);
    renderPanel(oneMode());

    await screen.findByRole("button", { name: "Svar klart" });
    api.POST.mockResolvedValue(ok({ ...CHAT, editing: false }));
    fireEvent.click(screen.getByRole("button", { name: "Svar klart" }));
    await waitFor(() => expect(api.POST).toHaveBeenCalledTimes(2));

    expect(announce).not.toHaveBeenCalled();
    expect(api.PATCH).not.toHaveBeenCalled();
  });

  it("sends at once for a page with nothing to do first", async () => {
    openChat(false);
    renderPanel(oneMode());
    expect(await screen.findByText("sends at once")).toBeTruthy();
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

describe("HelperPanel while a message is on its way", () => {
  it("holds a message the page holds back, and says why at the top of the panel until one goes", async () => {
    openChat(false);
    const reasons: (string | null)[] = ["Inställningarna kunde inte sparas.", null];
    const beforeSend = vi.fn(async () => reasons.shift() ?? null);
    renderPanel(adapter({ beforeSend }));

    fireEvent.click(await screen.findByRole("button", { name: "Skicka" }));
    await waitFor(() => expect(conversation.sent).toEqual([false]));
    const alerts = await screen.findAllByRole("alert");
    expect(alerts.map((alert) => alert.textContent).join(" ")).toContain(
      "Inställningarna kunde inte sparas."
    );
    expect(screen.getByText(messages.helper_send_held)).toBeTruthy();

    fireEvent.click(screen.getByRole("button", { name: "Skicka" }));
    await waitFor(() => expect(conversation.sent).toEqual([false, true]));
    expect(screen.queryByText("Inställningarna kunde inte sparas.")).toBeNull();
  });

  it("holds every message while the page's standing reason stands, without asking the page, and says why only while it stands", async () => {
    openChat(true);
    const beforeSend = vi.fn(async () => null);
    const panel = (sendHold: string | null) => (
      <HelperPanel adapter={adapter({ sendHold, beforeSend })} />
    );
    const { rerender } = renderInApp(panel("Spara ändringarna först."));

    fireEvent.click(await screen.findByRole("button", { name: "Skicka" }));
    await waitFor(() => expect(conversation.sent).toEqual([false]));
    expect(beforeSend).not.toHaveBeenCalled();
    const alerts = await screen.findAllByRole("alert");
    expect(alerts.map((alert) => alert.textContent).join(" ")).toContain(
      "Spara ändringarna först."
    );
    expect(screen.getByText(messages.helper_send_held)).toBeTruthy();

    // Saved: the notice goes before the next message, and new edits do not bring it back.
    rerender(panel(null));
    expect(screen.queryByText("Spara ändringarna först.")).toBeNull();
    rerender(panel("Spara ändringarna först."));
    expect(screen.queryByText("Spara ändringarna först.")).toBeNull();

    rerender(panel(null));
    fireEvent.click(screen.getByRole("button", { name: "Skicka" }));
    await waitFor(() => expect(conversation.sent).toEqual([false, true]));
    expect(beforeSend).toHaveBeenCalledTimes(1);
  });

  it("offers the page's way to its standing reason with the notice, and none with what beforeSend says", async () => {
    openChat(false);
    const onAction = vi.fn();
    const panel = (sendHold: string | null) => (
      <HelperPanel
        adapter={adapter({
          sendHold,
          sendHoldAction: { label: "Visa ändringarna", onAction },
          beforeSend: async () => "Inställningarna kunde inte sparas."
        })}
      />
    );
    const { rerender } = renderInApp(panel("Spara ändringarna först."));

    fireEvent.click(await screen.findByRole("button", { name: "Skicka" }));
    await waitFor(() => expect(conversation.sent).toEqual([false]));
    const notice = (await screen.findByText("Spara ändringarna först.")).closest(".astryx-banner");
    fireEvent.click(
      within(notice as HTMLElement).getByRole("button", { name: "Visa ändringarna" })
    );
    expect(onAction).toHaveBeenCalledTimes(1);
    // Nothing goes, and the notice stays while its reason stands.
    expect(conversation.sent).toEqual([false]);
    expect(screen.getByText("Spara ändringarna först.")).toBeTruthy();

    rerender(panel(null));
    fireEvent.click(screen.getByRole("button", { name: "Skicka" }));
    await waitFor(() => expect(conversation.sent).toEqual([false, false]));
    expect(await screen.findByText("Inställningarna kunde inte sparas.")).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Visa ändringarna" })).toBeNull();
  });

  it("reads the standing reason when a message goes, once its files are uploaded", async () => {
    openChat(false);
    const panel = (sendHold: string | null) => <HelperPanel adapter={adapter({ sendHold })} />;
    const { rerender } = renderInApp(panel(null));
    fireEvent.click(await screen.findByRole("button", { name: "Skicka med filer" }));

    rerender(panel("Spara ändringarna först."));
    fireEvent.click(screen.getByRole("button", { name: "Filerna uppladdade" }));
    await waitFor(() => expect(conversation.sent).toEqual([false]));
    expect(await screen.findByText("Spara ändringarna först.")).toBeTruthy();
  });

  it("holds a message sent while a mode is being saved until the save lands", async () => {
    openChat(false);
    let land!: (value: unknown) => void;
    api.PATCH.mockReturnValue(new Promise((resolve) => (land = resolve)));
    renderPanel();
    await pickEdit();
    expect(await screen.findByRole("button", { name: "Läge: Redigera" })).toBeTruthy();

    fireEvent.click(screen.getByRole("button", { name: "Skicka" }));
    await new Promise((resolve) => setTimeout(resolve, 20));
    expect(conversation.sent).toEqual([]);

    land(ok({ ...CHAT, editing: true }));
    await waitFor(() => expect(conversation.sent).toEqual([true]));
  });

  it("holds the message when the mode it waits for is refused, and shows the refusal", async () => {
    openChat(false);
    let land!: (value: unknown) => void;
    api.PATCH.mockReturnValue(new Promise((resolve) => (land = resolve)));
    const onRefused = vi.fn();
    renderPanel(adapter({ onRefused }));
    await pickEdit();
    fireEvent.click(await screen.findByRole("button", { name: "Skicka" }));

    land({
      error: { message: "Stale.", code: "stale", eneo_error_code: 9007 },
      response: new Response(null, { status: 409 })
    });

    await waitFor(() => expect(conversation.sent).toEqual([false]));
    expect(onRefused).toHaveBeenCalledTimes(1);
    expect(onRefused.mock.calls[0]![1]).toBe(messages.flows_notice_mode_not_changed);
    expect(await screen.findByRole("button", { name: "Läge: Fråga" })).toBeTruthy();
  });

  it("asks first on a target with modes, so a message can wait for a mode save", async () => {
    openChat(false);
    renderPanel();
    expect(await screen.findByText("asks before sending")).toBeTruthy();
  });
});

describe("HelperPanel's visits", () => {
  /** A target that starts each visit on a new conversation. */
  const freshApi = () => ({ ...flowHelperApi("flow-1"), freshPerVisit: true });
  const OPEN = "/api/v1/flows/{id}/authoring-chat/";

  it("asks for a fresh start on a visit's first read only, never on a read after an answer", async () => {
    openChat(false);
    renderPanel(adapter({ api: freshApi() }));
    expect(await screen.findByRole("button", { name: "Läge: Fråga" })).toBeTruthy();
    expect(api.POST).toHaveBeenCalledWith(OPEN, {
      params: { path: { id: "flow-1" }, query: { fresh_start: true } }
    });

    fireEvent.click(screen.getByRole("button", { name: "Svar klart" }));
    await waitFor(() => expect(api.POST).toHaveBeenCalledTimes(2));
    expect(api.POST).toHaveBeenLastCalledWith(OPEN, { params: { path: { id: "flow-1" } } });
  });

  it("forgets the chat when the panel goes, so the next visit asks afresh and shows none of it first", async () => {
    openChat(false);
    const queryClient = testQueryClient();
    const first = renderInApp(<HelperPanel adapter={adapter({ api: freshApi() })} />, {
      queryClient
    });
    expect(await screen.findByText(`partner: ${TEXTS.partnerName}`)).toBeTruthy();
    first.unmount();
    expect(queryClient.getQueryData(flowKeys.authoringChat("flow-1"))).toBeUndefined();

    let land!: (value: unknown) => void;
    api.POST.mockReturnValue(new Promise((resolve) => (land = resolve)));
    renderInApp(<HelperPanel adapter={adapter({ api: freshApi() })} />, { queryClient });
    expect(screen.getByText(messages.flows_chat_loading)).toBeTruthy();
    expect(screen.queryByText(`partner: ${TEXTS.partnerName}`)).toBeNull();
    expect(api.POST).toHaveBeenLastCalledWith(OPEN, {
      params: { path: { id: "flow-1" }, query: { fresh_start: true } }
    });

    land(ok({ ...CHAT, session_id: "session-2", editing: false }));
    expect(await screen.findByText(`partner: ${TEXTS.partnerName}`)).toBeTruthy();
  });

  it("resumes a target that does not start afresh, and keeps what it read", async () => {
    openChat(false);
    const queryClient = testQueryClient();
    const view = renderInApp(<HelperPanel adapter={adapter()} />, { queryClient });
    expect(await screen.findByRole("button", { name: "Läge: Fråga" })).toBeTruthy();

    expect(api.POST).toHaveBeenCalledWith(OPEN, { params: { path: { id: "flow-1" } } });
    view.unmount();
    expect(queryClient.getQueryData(flowKeys.authoringChat("flow-1"))).toBeDefined();
  });
});

describe("HelperPanel's earlier conversations", () => {
  const EARLIER = {
    session_id: "session-0",
    title: "Hur börjar flödet?",
    started_at: "2026-11-18T09:00:00Z",
    last_asked_at: "2026-11-18T09:05:00Z",
    current: false
  };

  /** The chat opens; the list holds one earlier conversation, which reads as one question and its answer. */
  function openWithHistory() {
    openChat(false);
    api.GET.mockImplementation(async (path: string, init?: { params?: { path?: object } }) => {
      if (path === "/api/v1/assistants/{id}/") {
        return ok({ id: "assistant-chat", name: "Medborgarbrev", mcp_servers: [] });
      }
      if (path === "/api/v1/flows/{id}/authoring-chat/conversations/") {
        return ok({ items: [{ ...EARLIER }], count: 1 });
      }
      const session = (init?.params?.path as { session_id?: string } | undefined)?.session_id;
      return session === "session-0"
        ? ok({
            id: "session-0",
            name: "",
            messages: [
              {
                id: "q-0",
                question: "Hur börjar flödet?",
                answer: "Med ett formulär.",
                created_at: "2026-11-18T09:05:00Z",
                updated_at: "2026-11-18T09:05:10Z"
              }
            ]
          })
        : ok({ id: "session-1", name: "", messages: [] });
    });
  }

  /** Picks the earlier conversation from the title row's menu. */
  async function pickEarlier() {
    fireEvent.click(await screen.findByRole("button", { name: messages.helper_history }));
    const item = await screen.findByRole("menuitem", { name: /Hur börjar flödet\?/ });
    // The menu takes the focus once it has opened, as it does before a person can pick.
    await waitFor(() => expect(document.activeElement?.closest("[role='menu']")).not.toBeNull());
    fireEvent.click(item);
    return screen.findByRole("heading", { level: 3, name: messages.helper_earlier_heading });
  }

  /** Whether the current conversation is out of sight. */
  const currentHidden = async () =>
    (await screen.findByText(`partner: ${TEXTS.partnerName}`)).closest("[hidden]") !== null;

  it("offers them only where the target lists its conversations", async () => {
    openChat(false);
    renderPanel(adapter({ api: { ...flowHelperApi("flow-1"), listConversations: undefined } }));

    expect(await screen.findByRole("button", { name: "Läge: Fråga" })).toBeTruthy();
    expect(screen.queryByRole("button", { name: messages.helper_history })).toBeNull();
  });

  it("shows a picked one read only, says so, and goes back to the composer", async () => {
    openWithHistory();
    renderPanel();

    const heading = await pickEarlier();
    await waitFor(() => expect(document.activeElement).toBe(heading));
    expect(announce).toHaveBeenCalledWith(
      expect.stringMatching(/^Du läser en tidigare konversation från .*2026/)
    );
    expect(await screen.findByText("Med ett formulär.")).toBeTruthy();
    expect(screen.getByRole("button", { name: messages.helper_earlier_back })).toBeTruthy();
    expect(screen.queryAllByRole("alert")).toEqual([]);
    expect(await currentHidden()).toBe(true);
    expect(screen.queryByRole("textbox", { name: "Meddelande" })).toBeNull();
    // The title row stays: a new conversation and the settings can be reached.
    expect(screen.getByRole("button", { name: messages.flows_chat_new_conversation })).toBeTruthy();

    fireEvent.click(screen.getByRole("button", { name: messages.helper_earlier_back }));

    expect(screen.queryByRole("heading", { name: messages.helper_earlier_heading })).toBeNull();
    expect(await currentHidden()).toBe(false);
    await waitFor(() =>
      expect(document.activeElement).toBe(screen.getByRole("textbox", { name: "Meddelande" }))
    );
  });

  it("gives way to the current conversation when the panel is put away, and to a new one", async () => {
    openWithHistory();
    const panel = (open: boolean) => <HelperPanel adapter={adapter()} open={open} />;
    const { rerender } = renderInApp(panel(true));

    await pickEarlier();
    rerender(panel(false));
    rerender(panel(true));
    expect(screen.queryByRole("heading", { name: messages.helper_earlier_heading })).toBeNull();
    expect(await currentHidden()).toBe(false);

    await pickEarlier();
    api.POST.mockResolvedValue(ok({ ...CHAT, session_id: "session-2", editing: false }));
    fireEvent.click(screen.getByRole("button", { name: messages.flows_chat_new_conversation }));
    fireEvent.click(
      within(await screen.findByRole("alertdialog")).getByRole("button", {
        name: messages.flows_chat_new_conversation_confirm
      })
    );
    await waitFor(() =>
      expect(screen.queryByRole("heading", { name: messages.helper_earlier_heading })).toBeNull()
    );
    expect(await currentHidden()).toBe(false);
  });

  it("brings the current conversation back for what the page puts in its composer", async () => {
    openWithHistory();
    const typed: string[] = [];
    conversation.composer = { insertText: (text) => typed.push(text), insertToken: () => {} };
    const onComposer = vi.fn();
    renderPanel(adapter({ references: { remarkPlugins: [], components: {}, onComposer } }));
    await waitFor(() => expect(onComposer).toHaveBeenLastCalledWith(conversation.composer));

    await pickEarlier();
    await waitFor(() => expect(onComposer.mock.lastCall?.[0]).not.toBe(conversation.composer));
    const standIn = onComposer.mock.lastCall?.[0] as { insertText: (text: string) => void };
    act(() => standIn.insertText("Hjälp mig med steg 2"));

    await waitFor(() => expect(typed).toEqual(["Hjälp mig med steg 2"]));
    expect(screen.queryByRole("heading", { name: messages.helper_earlier_heading })).toBeNull();
    expect(onComposer).toHaveBeenLastCalledWith(conversation.composer);
  });
});
