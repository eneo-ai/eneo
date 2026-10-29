// @vitest-environment jsdom
import type { WidgetClient, WidgetPublicConfig } from "@eneo/eneo-js";
import { afterEach, describe, expect, it, vi } from "vitest";
import { renderInApp } from "@/test/render";
import { personaView } from "../persona";
import { WidgetChat } from "./widget-chat";

// The bridge is replaced so the test can read what the page tells the loader
// at ready, which the real bridge only posts from inside an iframe.
const ready = vi.fn();
vi.mock("../embed-bridge", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../embed-bridge")>()),
  createEmbedBridge: () => ({
    embedded: true,
    post: vi.fn(),
    ready,
    close: vi.fn(),
    expand: vi.fn(),
    collapse: vi.fn(),
    conversationStarted: vi.fn(),
    destroy: vi.fn()
  })
}));

function config(persona: WidgetPublicConfig["persona"]): WidgetPublicConfig {
  return {
    public_id: "wgt_aaaaaaaaaaaaaaaaaaaaaa",
    name: "Kaffe",
    texts: {
      title: "Kaffehjälpen",
      subtitle: "",
      welcome: "Hej!",
      placeholder: "",
      suggested_questions: [],
      footer_text: "",
      footer_link_url: null,
      footer_link_label: null
    },
    theme: { color_scheme: "auto", primary_color: "#1F4E79", radius: 12 },
    persona,
    language: "sv",
    bot_protection: "none",
    max_question_chars: 1000,
    token_generation: 1,
    show_sources: true,
    show_tool_activity: true,
    collects_feedback_text: true,
    single_turn: false,
    frame_ancestors: []
  } as unknown as WidgetPublicConfig;
}

function renderChat(widget: WidgetPublicConfig) {
  return renderInApp(
    <WidgetChat
      config={widget}
      client={
        { conversations: { ask: vi.fn(), leaveFeedback: vi.fn() } } as unknown as WidgetClient
      }
      hostOrigin="https://www.kommun.se"
      onSession={() => {}}
      persona={personaView(widget)}
    />
  );
}

afterEach(() => {
  ready.mockClear();
});

describe("WidgetChat ready message", () => {
  it("gives the launcher the avatar as an absolute address when it should show it", () => {
    renderChat(config({ name: "Sigge", avatar_icon_id: "ic1", avatar_in_launcher: true }));
    expect(ready).toHaveBeenCalledOnce();
    const persona = ready.mock.calls[0]![2];
    expect(persona).toEqual({ name: "Sigge", avatar_url: expect.any(String) });
    // Relative on the page (its own proxy), absolute for the host page's launcher.
    expect(persona.avatar_url).toBe(new URL("/api/v1/icons/ic1/", location.origin).href);
    expect(persona.avatar_url).toMatch(/^https?:\/\//);
  });

  it("keeps the avatar off the launcher unless the persona asks for it", () => {
    renderChat(config({ name: "Sigge", avatar_icon_id: "ic1", avatar_in_launcher: false }));
    expect(ready.mock.calls[0]![2]).toEqual({ name: "Sigge", avatar_url: null });
  });
});
