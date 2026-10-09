/* eslint-disable eneo/no-raw-color -- fixtures use literal widget colours */
import { describe, expect, it, vi } from "vitest";
import * as loader from "../../../../../../packages/widget-loader/src/protocol";
import { launcherColors } from "./contrast";
import { BRIDGE_NAMESPACE, BRIDGE_VERSION, createEmbedBridge, parseInbound } from "./embedBridge";

const colors = {
  light: { accent: "#1F4E79", on_accent: "#FFFFFF" },
  dark: { accent: "#9CC7F0", on_accent: "#111111" }
};

/**
 * The v1 wire format, frozen. Pinned (SRI) loaders on customer sites send
 * and understand exactly these for years, and every embed page this
 * installation serves must keep talking to them. Never edit an entry: a
 * change an old side could misread takes BRIDGE_VERSION 2 and a new set.
 */
const V1 = {
  /** What a v1 loader sends the embed page. */
  host: [
    { ns: "eneo-widget", v: 1, type: "open" },
    { ns: "eneo-widget", v: 1, type: "theme", payload: { scheme: "light" } },
    { ns: "eneo-widget", v: 1, type: "theme", payload: { scheme: "dark" } },
    { ns: "eneo-widget", v: 1, type: "theme", payload: { scheme: "auto" } },
    {
      ns: "eneo-widget",
      v: 1,
      type: "context",
      payload: { page_url: "https://www.kommun.se/bygglov", page_title: "Bygglov" }
    }
  ],
  /** What the embed page sends a v1 loader. */
  frame: [
    { ns: "eneo-widget", v: 1, type: "ready" },
    { ns: "eneo-widget", v: 1, type: "ready", payload: { colors } },
    { ns: "eneo-widget", v: 1, type: "close" },
    { ns: "eneo-widget", v: 1, type: "conversation_started" },
    { ns: "eneo-widget", v: 1, type: "unread", payload: { count: 2 } }
  ]
} as const;

const unwrap = ({ ns: _ns, v: _v, ...message }: Record<string, unknown>) => message;

type Bridge = ReturnType<typeof createEmbedBridge>;

/** What the embed page's bridge posts to the host page while `send` runs. */
function posted(send: (bridge: Bridge) => void): Record<string, unknown>[] {
  const target = { postMessage: vi.fn() };
  send(
    createEmbedBridge({ hostOrigin: "https://www.kommun.se", target, addListener: () => () => {} })
  );
  return target.postMessage.mock.calls.map(([message]) => message);
}

/** Every message the embed page sends. */
const embedPageMessages = () =>
  posted((bridge) => {
    bridge.ready();
    bridge.ready(colors);
    bridge.close();
    bridge.conversationStarted();
    bridge.post({ type: "unread", payload: { count: 2 } });
  });

describe("bridge protocol between the embed page and the loader", () => {
  it("speaks one namespace and version on both sides", () => {
    expect(BRIDGE_NAMESPACE).toBe(loader.BRIDGE_NAMESPACE);
    expect(BRIDGE_VERSION).toBe(loader.BRIDGE_VERSION);
    expect(BRIDGE_VERSION).toBe(1);
  });

  it("has the embed page send exactly the frozen v1 messages", () => {
    expect(embedPageMessages()).toEqual(V1.frame);
  });

  it("has the loader read every message the embed page sends", () => {
    for (const message of [...embedPageMessages(), ...V1.frame]) {
      expect(loader.parseFrameMessage(message)).toEqual(unwrap(message));
    }
  });

  it("has the loader send exactly the frozen v1 messages", () => {
    const sent = V1.host.map((message) => loader.envelope(unwrap(message) as loader.HostMessage));
    expect(sent).toEqual(V1.host);
  });

  it("has the embed page read every message a v1 loader sends", () => {
    for (const message of V1.host) {
      expect(parseInbound(message)).toEqual(unwrap(message));
    }
  });

  it("has the loader accept the launcher colours the embed page computes", () => {
    for (const theme of [
      {},
      { primary_color: "#1F4E79" },
      { primary_color: "#FFD700", primary_color_dark: "#123456", color_scheme: "auto" as const },
      { primary_color: "#1F4E79", color_scheme: "dark" as const }
    ]) {
      const [message] = posted((bridge) => bridge.ready(launcherColors(theme)));
      expect(loader.parseFrameMessage(message)).toEqual({
        type: "ready",
        payload: { colors: launcherColors(theme) }
      });
    }
  });
});
