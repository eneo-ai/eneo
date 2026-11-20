// @vitest-environment jsdom
import { cleanup, fireEvent, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { ToolCallRecord } from "@/features/chat/side-panel/message-tool-calls";
import { API_KEYS_KEY, API_KEY_SUBSCRIPTIONS_KEY } from "@/features/api-keys/api-keys";
import { HelperPanel } from "@/features/helper/helper-panel";
import { EneoApiError } from "@/lib/api/errors";
import messages from "@/lib/i18n/messages/sv.json";
import { renderHookInApp, renderInApp, testQueryClient } from "@/test/render";
import type { AssistantHelperAvailability } from "./assistant-helper-api";
import { AssistantHelperToggle, useAssistantHelper } from "./assistant-helper";
import type { Assistant } from "./use-assistant";

const api = vi.hoisted(() => ({ GET: vi.fn(), POST: vi.fn(), PATCH: vi.fn() }));
const toast = vi.hoisted(() => ({ error: vi.fn(), success: vi.fn(), info: vi.fn() }));

vi.mock("@/lib/api/browser", () => ({ browserApi: api }));
vi.mock("@/lib/toast", () => ({ toast }));
vi.mock("@/lib/navigation", () => import("@/test/navigation"));
vi.mock("@/features/spaces/use-space", async () => {
  const { useSpaceFromQuery } = await import("@/features/spaces/testing/space-query");
  const { makeSpace } = await import("@/features/spaces/testing/space-fixture");
  return { useSpace: () => useSpaceFromQuery(() => makeSpace()) };
});
// The conversation is the chat feature's: the panel decides its welcome, footer and placeholder.
vi.mock("@/features/chat/chat-view", () => ({
  ChatView: ({
    placeholder,
    partner,
    footerActions
  }: {
    placeholder?: string;
    partner?: { name?: string; description?: string };
    footerActions?: unknown;
  }) => (
    <div>
      <p>partner: {partner?.name}</p>
      <p>{partner?.description}</p>
      {footerActions as React.ReactNode}
      <p>{placeholder}</p>
    </div>
  )
}));

const ID = "assistant-1";
const ASSISTANT = { id: ID, name: "Skolhjälpen", permissions: ["read", "edit"] } as Assistant;
const ok = (data: unknown) => ({ data, response: new Response(null, { status: 200 }) });
const CHAT = {
  target_id: ID,
  assistant_id: "helper-assistant",
  session_id: "session-1"
};

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe("The editor's Hjälpassistent toggle", () => {
  function renderToggle(
    availability: AssistantHelperAvailability | undefined,
    open = false,
    compact = false
  ) {
    const onOpenChange = vi.fn();
    renderInApp(
      <AssistantHelperToggle
        availability={availability}
        open={open}
        onOpenChange={onOpenChange}
        compact={compact}
      />
    );
    return onOpenChange;
  }

  it("is not there while the availability is not known", () => {
    renderToggle(undefined);
    expect(screen.queryByRole("button")).toBeNull();
  });

  it("opens and closes the helper where it is available, pressed while it is open", () => {
    const onOpenChange = renderToggle({ available: true });
    const toggle = screen.getByRole("button", { name: "Hjälpassistent" });
    expect(toggle.getAttribute("aria-pressed")).toBe("false");
    fireEvent.click(toggle);
    expect(onOpenChange).toHaveBeenCalledWith(true);
    cleanup();

    renderToggle({ available: true }, true);
    expect(
      screen.getByRole("button", { name: "Hjälpassistent" }).getAttribute("aria-pressed")
    ).toBe("true");
  });

  it("is disabled, saying why, while the space has no model for it", () => {
    const onOpenChange = renderToggle({ available: false, reason: "no_model" });
    const toggle = screen.getByRole("button", { name: "Hjälpassistent" });

    expect(toggle.getAttribute("aria-disabled")).toBe("true");
    const description = toggle
      .getAttribute("aria-describedby")!
      .split(" ")
      .map((id) => document.getElementById(id)?.textContent)
      .join(" ");
    expect(description).toContain(
      "Ytan har ingen modell som kan använda verktyg. Be en administratör för ytan att lägga till en."
    );
    fireEvent.click(toggle);
    expect(onOpenChange).not.toHaveBeenCalled();
  });

  it("leaves a disabled toggle out of a phone's bar, where its reason could not be reached", () => {
    renderToggle({ available: false, reason: "no_model" }, false, true);
    expect(screen.queryByRole("button")).toBeNull();
    cleanup();

    renderToggle({ available: true }, false, true);
    expect(screen.getByRole("button", { name: "Hjälpassistent" })).toBeTruthy();
  });

  it("is not there for someone who may not edit the assistant, or one set up elsewhere", () => {
    renderToggle({ available: false, reason: "no_edit_rights" });
    expect(screen.queryByRole("button")).toBeNull();
    cleanup();
    renderToggle({ available: false, reason: "not_supported" });
    expect(screen.queryByRole("button")).toBeNull();
  });

  it("is not there when the organisation has turned the helper off", () => {
    renderToggle({ available: false, reason: "disabled" });
    expect(screen.queryByRole("button")).toBeNull();
  });
});

describe("The assistant's helper adapter", () => {
  const call = (serverName: string, isInternal = true) =>
    ({ serverName, isInternal, toolName: "update_assistant" }) as ToolCallRecord;

  it("says why the helper is not open, for each reason the availability gives", () => {
    const unavailable = (availability: AssistantHelperAvailability | undefined) =>
      renderHookInApp(() => useAssistantHelper({ assistant: ASSISTANT, availability })).result
        .current.unavailable;

    expect(unavailable(undefined)).toBeNull();
    expect(unavailable({ available: true })).toBeNull();
    expect(unavailable({ available: false, reason: "no_model" })).toBe(
      "Ytan har ingen modell som kan använda verktyg. Be en administratör för ytan att lägga till en."
    );
    expect(unavailable({ available: false, reason: "no_edit_rights" })).toBe(
      "Du får inte ändra den här assistenten, så hjälpassistenten är inte öppen för dig."
    );
    expect(unavailable({ available: false, reason: "not_supported" })).toBe(
      "Den här assistenten ställs in på annat håll, så den har ingen hjälpassistent."
    );
    expect(unavailable({ available: false, reason: "disabled" })).toBe(
      "Organisationen har stängt av hjälpassistenten."
    );
  });

  it("puts the chat's refusals in plain words, and shows a refused change in a toast", () => {
    const { result } = renderHookInApp(() =>
      useAssistantHelper({ assistant: ASSISTANT, availability: { available: true } })
    );
    const { refusalText, onRefused } = result.current;

    expect(refusalText?.("helper_chat_model_without_tools")).toBe(
      "Modellen kan inte använda verktyg. Välj en annan modell för hjälpassistenten."
    );
    expect(refusalText?.("something_else")).toBeNull();

    onRefused(
      new EneoApiError("The model is not enabled.", {
        status: 400,
        reason: "helper_chat_model_not_in_space"
      }),
      "Modellen ändrades inte"
    );
    expect(toast.error).toHaveBeenCalledWith(
      "Modellen ändrades inte",
      expect.objectContaining({
        description: expect.stringContaining(
          "Modellen är inte aktiverad i ytan. Välj en annan modell."
        )
      })
    );
  });

  it("reads the assistant and its space again after a call of the assistant server and an answer", () => {
    const queryClient = testQueryClient();
    const invalidate = vi.spyOn(queryClient, "invalidateQueries");
    const { result } = renderHookInApp(
      () => useAssistantHelper({ assistant: ASSISTANT, availability: { available: true } }),
      { queryClient }
    );
    invalidate.mockClear();

    result.current.onToolCallFinished?.(call("assistant"));
    expect(invalidate.mock.calls.map(([filters]) => filters?.queryKey)).toEqual([
      ["assistants", ID],
      ["spaces", "space-1"]
    ]);

    invalidate.mockClear();
    result.current.onAnswerFinished?.();
    expect(invalidate.mock.calls.map(([filters]) => filters?.queryKey)).toEqual([
      ["assistants", ID],
      ["spaces", "space-1"]
    ]);
  });

  it("after a publish also reads the API keys' expiry notices again, and hands the publish on", () => {
    const queryClient = testQueryClient();
    const invalidate = vi.spyOn(queryClient, "invalidateQueries");
    const onChanged = vi.fn();
    const { result } = renderHookInApp(
      () =>
        useAssistantHelper({ assistant: ASSISTANT, availability: { available: true }, onChanged }),
      { queryClient }
    );
    invalidate.mockClear();

    result.current.onToolCallFinished?.({
      serverName: "assistant",
      isInternal: true,
      toolName: "publish_assistant",
      structuredContent: {
        target_id: ID,
        changes: [{ field: "published", before: false, after: true }],
        undo: null
      }
    } as unknown as ToolCallRecord);

    expect(invalidate.mock.calls.map(([filters]) => filters?.queryKey)).toEqual([
      ["assistants", ID],
      ["spaces", "space-1"],
      API_KEY_SUBSCRIPTIONS_KEY,
      [...API_KEYS_KEY, "expiring-soon"]
    ]);
    expect(onChanged).toHaveBeenCalledWith(["published"]);
  });

  it("leaves the assistant alone after another server's call, or one named like its own", () => {
    const queryClient = testQueryClient();
    const invalidate = vi.spyOn(queryClient, "invalidateQueries");
    const { result } = renderHookInApp(
      () => useAssistantHelper({ assistant: ASSISTANT, availability: { available: true } }),
      { queryClient }
    );
    invalidate.mockClear();

    result.current.onToolCallFinished?.(call("knowledge"));
    result.current.onToolCallFinished?.(call("flows"));
    result.current.onToolCallFinished?.(call("assistant", false));
    expect(invalidate).not.toHaveBeenCalled();
  });
});

describe("The helper panel on an assistant", () => {
  function Panel({ availability }: { availability: AssistantHelperAvailability }) {
    return <HelperPanel adapter={useAssistantHelper({ assistant: ASSISTANT, availability })} />;
  }

  function openChat(chat: typeof CHAT) {
    api.POST.mockResolvedValue(ok(chat));
    api.GET.mockImplementation(async (path: string) =>
      path === "/api/v1/assistants/{id}/"
        ? ok({ id: "helper-assistant", name: "Skolhjälpen", mcp_servers: [] })
        : ok({ id: "session-1", name: "", messages: [] })
    );
  }

  it("opens the assistant's chat on a new conversation, in its own words, where it is available", async () => {
    openChat(CHAT);
    renderInApp(<Panel availability={{ available: true }} />);

    expect(await screen.findByText("partner: Hjälpassistenten")).toBeTruthy();
    expect(screen.getByRole("heading", { level: 2, name: "Hjälpassistent" })).toBeTruthy();
    expect(screen.getByText(messages.helper_placeholder)).toBeTruthy();
    expect(screen.getByText(messages.helper_partner_description)).toBeTruthy();
    expect(api.POST).toHaveBeenCalledWith("/api/v1/assistants/{id}/helper-chat/", {
      params: { path: { id: ID }, query: { fresh_start: true } }
    });
    expect(screen.getByRole("button", { name: messages.helper_history })).toBeTruthy();
  });
});
