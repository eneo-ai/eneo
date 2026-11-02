// @vitest-environment jsdom
import { act, cleanup, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { Schema } from "@/lib/api/models";
import type { ChatPartner } from "@/lib/chat/types";
import { renderInApp, testAppContext } from "@/test/render";
import {
  ConversationSettingsProvider,
  useConversationSettings,
  useAutomaticConversationTools
} from "./conversation-settings";
import { useToolChoices } from "./use-tool-choices";

const api = vi.hoisted(() => ({ POST: vi.fn(), PATCH: vi.fn() }));
vi.mock("@/lib/api/browser", () => ({ browserApi: api }));
vi.mock("next/navigation", () => import("@/test/navigation"));
let supportsTools = true;
let saved: Schema<"ConversationSettingsState">;
const defaults: Schema<"ConversationSettings"> = {
  completion_model_id: "model-1",
  require_tool_approval: false,
  mcp_server_states: { diarium: true, kalender: false },
  capability_states: { web_search: true, image_generation: true }
};
beforeEach(() => {
  supportsTools = true;
  saved = { revision: 2, settings: structuredClone(defaults) };
  api.POST.mockImplementation(async (_path, { body }) => ({
    data: {
      revision: body.session_id ? saved.revision : 0,
      settings: body.session_id ? saved.settings : (body.settings ?? structuredClone(defaults)),
      supports_tool_calling: supportsTools,
      mcp_servers: personal.mcpServers?.map((server) => ({
        ...server,
        selected:
          (body.session_id ? saved.settings : (body.settings ?? defaults)).mcp_server_states?.[
            server.id
          ] ?? true,
        available: supportsTools,
        reason: supportsTools ? null : "model_no_tool_calling"
      })),
      capabilities: personal.availableCapabilities?.map((capability) => ({
        ...capability,
        selected:
          (body.session_id ? saved.settings : (body.settings ?? defaults)).capability_states?.[
            capability.purpose
          ] ?? true,
        available: supportsTools,
        reason: supportsTools ? null : "model_no_tool_calling"
      })),
      available_models: [{ id: "model-1" }, { id: "model-2" }],
      effective_model: { id: body.settings?.completion_model_id ?? "model-1" },
      model_unavailable: false
    },
    response: new Response()
  }));
  api.PATCH.mockImplementation(async (_path, { body }) => {
    if (body.expected_revision !== saved.revision)
      return { error: { message: "Conflict" }, response: new Response(null, { status: 409 }) };
    saved = { revision: saved.revision + 1, settings: body.settings };
    return { data: saved, response: new Response() };
  });
});
afterEach(() => {
  cleanup();
  vi.clearAllMocks();
  window.localStorage.clear();
});

const server = (id: string): Schema<"MCPServerPublicDict"> => ({
  id,
  name: id,
  description: null,
  http_url: null,
  http_auth_type: null,
  purpose: "general",
  is_enabled: true,
  readiness_reason: null,
  tags: null,
  icon_url: null,
  security_classification: null,
  tools: []
});

const personal: ChatPartner = {
  type: "default-assistant",
  id: "personal-1",
  name: "Personlig assistent",
  enabledCapabilities: ["web_search", "image_generation"],
  availableCapabilities: [
    { purpose: "web_search", available: true, reason: null },
    { purpose: "image_generation", available: true, reason: null }
  ],
  mcpServers: [server("diarium"), server("kalender")]
};

function renderChoices(partner: ChatPartner = personal, sessionId: string | null = null) {
  let latest: {
    tools: ReturnType<typeof useToolChoices>;
    settings: ReturnType<typeof useConversationSettings>;
    automatic: boolean;
  };
  function Probe() {
    latest = {
      tools: useToolChoices(),
      settings: useConversationSettings(),
      automatic: useAutomaticConversationTools()
    };
    return null;
  }
  const view = renderInApp(
    <ConversationSettingsProvider partner={partner} initialSessionId={sessionId}>
      <Probe />
    </ConversationSettingsProvider>,
    {
      appContext: testAppContext({ permissions: ["web_search", "image_generation"] })
    }
  );
  return {
    ...view,
    get current() {
      return latest;
    }
  };
}

async function ready(view: ReturnType<typeof renderChoices>) {
  await waitFor(() => expect(view.current.settings.busy).toBe(false));
}

describe("conversation choices", () => {
  it("uses backend selection even when saved maps are empty and a tool is unavailable", async () => {
    api.POST.mockResolvedValueOnce({
      data: {
        revision: 2,
        settings: {},
        mcp_servers: [{ id: "diarium", name: "diarium", available: false, selected: true }],
        capabilities: [{ purpose: "web_search", available: true, selected: false }]
      },
      response: new Response()
    });
    const view = renderChoices(personal, "saved");
    await ready(view);
    expect(view.current.tools.disabledMcpServerIds.has("diarium")).toBe(false);
    expect(view.current.tools.mcpServers[0]?.available).toBe(false);
    expect(view.current.tools.disabledCapabilities.has("web_search")).toBe(true);
  });

  it("blocks edits and automatic tool calls for an incompatible stored configuration", async () => {
    api.POST.mockResolvedValueOnce({
      data: { ...saved, settings_compatible: false },
      response: new Response()
    });
    const view = renderChoices(personal, "saved");
    await ready(view);
    expect(view.current.settings.resolution?.settings_compatible).toBe(false);
    expect(view.current.automatic).toBe(false);
    await act(async () => view.current.settings.update({ require_tool_approval: false }));
    expect(api.PATCH).not.toHaveBeenCalled();
  });
  it("saves bulk tools atomically and restores them when the same conversation is opened again", async () => {
    const first = renderChoices(personal, "saved");
    await ready(first);
    await act(async () =>
      first.current.tools.setTools(new Set(["diarium"]), new Set(["web_search"]))
    );
    await ready(first);
    expect(api.PATCH).toHaveBeenCalledTimes(1);
    expect(saved.settings.mcp_server_states).toEqual({ diarium: false, kalender: true });
    first.unmount();
    const second = renderChoices(personal, "saved");
    await ready(second);
    expect([...second.current.tools.disabledMcpServerIds]).toEqual(["diarium"]);
    expect([...second.current.tools.disabledCapabilities]).toEqual(["web_search"]);
  });

  it("lets a legacy conversation replace an unavailable default before its first save", async () => {
    saved = { revision: 0, settings: { completion_model_id: "removed" } };
    api.POST.mockResolvedValueOnce({
      data: {
        ...saved,
        model_unavailable: true,
        available_models: [{ id: "model-2" }]
      },
      response: new Response()
    });
    const view = renderChoices(personal, "legacy");
    await ready(view);
    expect(api.PATCH).not.toHaveBeenCalled();
    expect(view.current.settings.error).toBeNull();
    expect(view.current.settings.resolution?.available_models?.[0]?.id).toBe("model-2");
    await act(async () => view.current.settings.update({ completion_model_id: "model-2" }));
    expect(saved.revision).toBe(1);
    expect(view.current.settings.resolution?.settings.completion_model_id).toBe("model-2");
  });

  it("remembers browser choices for new drafts without saving them on the server", async () => {
    window.localStorage.setItem("autoAcceptToolsEnabled", "false");
    const first = renderChoices();
    await ready(first);
    await act(async () => first.current.tools.setAutoAcceptTools(false));
    await act(async () => first.current.settings.update({ completion_model_id: "model-2" }));
    await ready(first);
    expect(first.current.automatic).toBe(false);
    expect(api.PATCH).not.toHaveBeenCalled();
    first.unmount();
    const next = renderChoices();
    await ready(next);
    expect(next.current.automatic).toBe(false);
    expect(next.current.settings.resolution?.settings.completion_model_id).toBe("model-2");
    expect(api.PATCH).not.toHaveBeenCalled();
    next.unmount();
    window.localStorage.clear();
    const reset = renderChoices();
    await ready(reset);
    expect(reset.current.automatic).toBe(true);
    expect(reset.current.settings.resolution?.settings.completion_model_id).toBe("model-1");
  });

  it("keeps stored conversation choices authoritative over browser start choices", async () => {
    const draft = renderChoices();
    await ready(draft);
    await act(async () =>
      draft.current.settings.update({ completion_model_id: "model-2", require_tool_approval: true })
    );
    draft.unmount();
    const existing = renderChoices(personal, "saved");
    await ready(existing);
    expect(existing.current.settings.resolution?.settings.completion_model_id).toBe("model-1");
    expect(existing.current.automatic).toBe(true);
  });

  it("keeps dormant choices while the model cannot call tools", async () => {
    supportsTools = false;
    saved.settings.mcp_server_states = {
      diarium: false,
      kalender: true,
      temporarily_removed: true
    };
    const view = renderChoices(
      {
        ...personal,
        completionModel: { id: "plain", name: "Plain", supports_tool_calling: false }
      },
      "saved"
    );
    await ready(view);
    expect(view.current.tools.capabilities.every((c) => !c.available)).toBe(true);
    await act(async () => view.current.tools.setAutoAcceptTools(false));
    await ready(view);
    expect(saved.settings.mcp_server_states).toEqual({
      diarium: false,
      kalender: true,
      temporarily_removed: true
    });
  });

  it("reports revision conflicts and reloads instead of overwriting another client", async () => {
    const view = renderChoices(personal, "saved");
    await ready(view);
    saved = { revision: 3, settings: { ...defaults, require_tool_approval: true } };
    await act(async () => view.current.settings.update({ reasoning_effort: "high" }));
    expect(view.current.settings.error).toBeTruthy();
    expect(view.current.automatic).toBe(false);
    expect(saved.settings.reasoning_effort).toBeUndefined();
    await act(async () => view.current.settings.reload());
    expect(view.current.settings.resolution?.revision).toBe(3);
    expect(view.current.settings.error).toBeNull();
  });

  it("takes the server's streamed revision before the next save", async () => {
    const view = renderChoices();
    await ready(view);
    await act(async () => view.current.settings.adoptSession("created", saved));
    await act(async () => view.current.settings.update({ completion_model_id: "model-2" }));
    expect(api.PATCH).toHaveBeenCalledWith(
      "/api/v1/conversations/{session_id}/settings/",
      expect.objectContaining({
        params: { path: { session_id: "created" } },
        body: expect.objectContaining({ expected_revision: 2 })
      })
    );
    expect(view.current.settings.resolution?.revision).toBe(3);
  });

  it("pins only the tool the user toggled; the others keep following the administrator's default", async () => {
    saved = {
      revision: 2,
      settings: { ...defaults, mcp_server_states: {}, capability_states: {} }
    };
    const view = renderChoices(personal, "saved");
    await ready(view);
    await act(async () => view.current.tools.toggleCapability("web_search"));
    await ready(view);
    expect(saved.settings.capability_states).toEqual({ web_search: false });
    expect(saved.settings.mcp_server_states).toEqual({});
    await act(async () => view.current.tools.setDisabledMcpServerIds(new Set(["kalender"])));
    await ready(view);
    expect(saved.settings.mcp_server_states).toEqual({ kalender: false });
    expect(saved.settings.capability_states).toEqual({ web_search: false });
  });

  it("leaves the browser's start choices alone until the user changes something", async () => {
    const draftKeys = () =>
      Object.keys(window.localStorage).filter((key) => key.startsWith("eneo:conversation-draft:"));
    const view = renderChoices();
    await ready(view);
    expect(draftKeys()).toEqual([]);
    await act(async () => view.current.settings.update({ completion_model_id: "model-2" }));
    expect(draftKeys()).toHaveLength(1);
  });

  it("saves two quick changes one after another, each on the revision the first produced", async () => {
    saved = { revision: 1, settings: structuredClone(defaults) };
    const view = renderChoices(personal, "saved");
    await ready(view);
    await act(async () => {
      void view.current.settings.update({ require_tool_approval: true });
      void view.current.settings.update({ reasoning_effort: "high" });
    });
    await ready(view);
    expect(api.PATCH.mock.calls.map(([, init]) => init.body.expected_revision)).toEqual([1, 2]);
    expect(saved).toMatchObject({
      revision: 3,
      settings: { require_tool_approval: true, reasoning_effort: "high" }
    });
    expect(view.current.settings.error).toBeNull();
    expect(view.current.settings.resolution?.revision).toBe(3);
  });

  it("refreshes in the background without going busy, and ignores a failed refresh", async () => {
    const view = renderChoices(personal, "saved");
    await ready(view);
    let release!: () => void;
    const held = new Promise<void>((resolve) => {
      release = resolve;
    });
    api.POST.mockImplementationOnce(async () => {
      await held;
      return { data: { ...saved, revision: 5 }, response: new Response() };
    });
    let refreshed!: Promise<void>;
    await act(async () => {
      refreshed = view.current.settings.refresh();
    });
    await waitFor(() => expect(api.POST).toHaveBeenCalledTimes(2));
    expect(view.current.settings.busy).toBe(false);
    expect(view.current.settings.resolution?.revision).toBe(2);
    await act(async () => {
      release();
      await refreshed;
    });
    expect(view.current.settings.resolution?.revision).toBe(5);

    api.POST.mockResolvedValueOnce({
      error: { message: "Gone" },
      response: new Response(null, { status: 500 })
    });
    await act(async () => view.current.settings.refresh());
    expect(view.current.settings.error).toBeNull();
    expect(view.current.settings.busy).toBe(false);
    expect(view.current.settings.resolution?.revision).toBe(5);
  });
});
