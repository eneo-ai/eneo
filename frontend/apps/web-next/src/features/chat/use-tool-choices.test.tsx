// @vitest-environment jsdom
import { act, cleanup, renderHook } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, describe, expect, it } from "vitest";
import type { AppContextData } from "@/components/providers/app-context";
import type { Schema } from "@/lib/api/models";
import type { ChatPartner } from "@/lib/chat/types";
import { ChatTestProviders, testAppContext } from "./testing";
import { useToolChoices } from "./use-tool-choices";

afterEach(() => {
  cleanup();
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

function contextWith(showWebSearch: boolean): AppContextData {
  return {
    ...testAppContext,
    user: { ...testAppContext.user, roles: [{ permissions: ["web_search", "image_generation"] }] },
    featureFlags: { ...testAppContext.featureFlags, showWebSearch }
  } as AppContextData;
}

function renderChoices(partner: ChatPartner, showWebSearch = true) {
  const appContext = contextWith(showWebSearch);
  const wrapper = ({ children }: { children: ReactNode }) => (
    <ChatTestProviders appContext={appContext}>{children}</ChatTestProviders>
  );
  return renderHook(() => useToolChoices(partner), { wrapper });
}

describe("useToolChoices", () => {
  it("remembers the personal assistant's choices for the next conversation", () => {
    const first = renderChoices(personal);
    act(() => first.result.current.toggleCapability("image_generation"));
    act(() => first.result.current.setDisabledMcpServerIds(new Set(["kalender"])));
    expect([...first.result.current.disabledCapabilities]).toEqual(["image_generation"]);
    first.unmount();

    const next = renderChoices(personal);
    expect([...next.result.current.disabledCapabilities]).toEqual(["image_generation"]);
    expect([...next.result.current.disabledMcpServerIds]).toEqual(["kalender"]);
  });

  it("does not remember choices made with a space assistant", () => {
    const assistant: ChatPartner = { ...personal, type: "assistant", id: "assistant-1" };
    const first = renderChoices(assistant);
    act(() => first.result.current.toggleCapability("web_search"));
    first.unmount();

    expect(renderChoices(assistant).result.current.disabledCapabilities.size).toBe(0);
  });

  it("hides web search when the deployment does not offer it", () => {
    const { result } = renderChoices(personal, false);
    expect(result.current.capabilities.map((capability) => capability.purpose)).toEqual([
      "image_generation"
    ]);
  });

  it("keeps the auto-approve choice across conversations", () => {
    const first = renderChoices(personal);
    expect(first.result.current.autoAcceptTools).toBe(true);
    act(() => first.result.current.setAutoAcceptTools(false));
    first.unmount();

    expect(renderChoices(personal).result.current.autoAcceptTools).toBe(false);
  });
});
