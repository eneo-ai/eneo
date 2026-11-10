// @vitest-environment jsdom
import { cleanup, fireEvent, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import messages from "@/lib/i18n/messages/sv.json";
import { renderInApp } from "@/test/render";
import { FlowChatPanel } from "./flow-chat-panel";
import { makeFlow, makeStep } from "./flow-fixtures";
import type { FlowPublic } from "./flows-api";

const api = vi.hoisted(() => ({ GET: vi.fn(), POST: vi.fn(), PATCH: vi.fn() }));

vi.mock("@/lib/api/browser", () => ({ browserApi: api }));
vi.mock("@/lib/navigation", () => import("@/test/navigation"));
vi.mock("@/features/spaces/use-space", async () => {
  const { useSpaceFromQuery } = await import("@/features/spaces/testing/space-query");
  const { makeSpace } = await import("@/features/spaces/testing/space-fixture");
  // A personal space: its own chat lists other conversations, the flow chat must not.
  return { useSpace: () => useSpaceFromQuery(() => makeSpace({ overrides: { personal: true } })) };
});
// The conversation is the chat feature's; the panel decides its welcome, footer and placeholder.
vi.mock("@/features/chat/chat-view", () => ({
  ChatView: ({
    footerActions,
    placeholder,
    composerLabel,
    partner
  }: {
    footerActions?: unknown;
    placeholder?: string;
    composerLabel?: string;
    partner?: { description?: string; personalSpace?: boolean };
  }) => (
    <div>
      <p>{partner?.description}</p>
      {partner?.personalSpace ? <p>personal lists</p> : null}
      {footerActions as React.ReactNode}
      <p>{placeholder}</p>
      <p>composer: {composerLabel ?? "partner"}</p>
    </div>
  )
}));

function refuseChat(body: Record<string, unknown>) {
  api.POST.mockResolvedValue({ error: body, response: new Response(null, { status: 400 }) });
}

function renderPanel(flow: FlowPublic = makeFlow(), onAskChat?: (text: string) => void) {
  return renderInApp(
    <FlowChatPanel
      flow={flow}
      onFlowMayHaveChanged={() => {}}
      onRefused={() => {}}
      onComposer={() => {}}
      onAskChat={onAskChat}
    />
  );
}

/** The chat opens, with its assistant and an empty conversation, in the given mode. */
function openChat(editing: boolean) {
  const ok = (data: unknown) => ({ data, response: new Response(null, { status: 200 }) });
  api.POST.mockResolvedValue(
    ok({ flow_id: "flow-1", assistant_id: "assistant-chat", session_id: "session-1", editing })
  );
  api.GET.mockImplementation(async (path: string) =>
    path === "/api/v1/assistants/{id}/"
      ? ok({ id: "assistant-chat", name: "Medborgarbrev", mcp_servers: [] })
      : ok({ id: "session-1", name: "", messages: [] })
  );
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

describe("FlowChatPanel when the chat cannot open", () => {
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

  it("gives a missing model its own text, as information", async () => {
    refuseChat({
      message: "No model.",
      code: "flow_authoring_chat_no_model",
      eneo_error_code: 9007
    });
    renderPanel();

    expect(await bannerStatus(messages.flows_chat_no_model)).toBe("info");
  });

  it("uses the flow catalog's sentence for a refusal it has one for", async () => {
    refuseChat({
      message: "The reasoning effort is not supported.",
      code: "flow_authoring_reasoning_effort_unsupported",
      eneo_error_code: 9007
    });
    renderPanel();

    expect(
      await screen.findByText(messages.flow_error_flow_authoring_reasoning_effort_unsupported)
    ).toBeTruthy();
    expect(screen.queryByText(/not supported/)).toBeNull();
  });

  it("never shows the core's English for a refusal it has no text for", async () => {
    refuseChat({ message: "Something internal went sideways.", code: "brand_new_refusal" });
    renderPanel();

    expect(await screen.findByText(messages.request_failed)).toBeTruthy();
    expect(screen.queryByText(/sideways/)).toBeNull();
  });
});

describe("FlowChatPanel on a published flow", () => {
  it("says the chat cannot change it and offers no edit mode, even one saved before", async () => {
    openChat(true);
    renderPanel(makeFlow({ published_version: 1 }));

    expect(await screen.findByText(messages.flows_chat_published_intro)).toBeTruthy();
    fireEvent.click(await screen.findByRole("button", { name: "Läge: Fråga" }));
    const edit = await screen.findByRole("menuitemradio", { name: /Redigera/ });
    expect(edit.getAttribute("aria-disabled")).toBe("true");
    expect(edit.textContent).toContain(messages.flows_chat_mode_edit_published);
    expect(screen.getByText(messages.flows_chat_placeholder_ask)).toBeTruthy();
    expect(screen.getByText("composer: partner")).toBeTruthy();
    // The welcome promises no changes either.
    expect(screen.getByText(messages.flows_chat_partner_description_published)).toBeTruthy();
    expect(screen.queryByText(messages.flows_chat_partner_description)).toBeNull();
  });

  it("keeps a draft's saved edit mode, without an intro", async () => {
    openChat(true);
    renderPanel(makeFlow({ published_version: null }));

    expect(await screen.findByRole("button", { name: "Läge: Redigera" })).toBeTruthy();
    expect(screen.getByText(messages.flows_chat_placeholder_edit)).toBeTruthy();
    expect(screen.queryByText(messages.flows_chat_published_intro)).toBeNull();
    expect(screen.getByText(messages.flows_chat_partner_description)).toBeTruthy();
    // The composer is named by what a message does in Redigera.
    expect(screen.getByText(`composer: ${messages.flows_chat_composer_label_edit}`)).toBeTruthy();
    // In a personal space too, the flow chat lists no other conversations.
    expect(screen.queryByText("personal lists")).toBeNull();
  });

  it("promises building steps only in Redigera", async () => {
    openChat(false);
    renderPanel(makeFlow({ published_version: null }));

    expect(await screen.findByRole("button", { name: "Läge: Fråga" })).toBeTruthy();
    expect(screen.getByText(messages.flows_chat_partner_description_ask)).toBeTruthy();
    expect(screen.queryByText(messages.flows_chat_partner_description)).toBeNull();
  });
});

describe("FlowChatPanel's Optimera flödet", () => {
  it("is offered only once the flow has a step", async () => {
    openChat(false);
    const { unmount } = renderPanel(makeFlow({ steps: [] }), () => {});
    expect(await screen.findByRole("button", { name: "Läge: Fråga" })).toBeTruthy();
    expect(screen.queryByRole("button", { name: messages.flow_suggestions_optimize })).toBeNull();
    unmount();

    renderPanel(makeFlow({ steps: [makeStep(1)] }), () => {});
    expect(
      await screen.findByRole("button", { name: messages.flow_suggestions_optimize })
    ).toBeTruthy();
  });
});
