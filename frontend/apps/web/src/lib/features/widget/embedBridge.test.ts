/* eslint-disable eneo/no-raw-color -- fixtures use literal widget colours */
import { describe, expect, it, vi } from "vitest";
import { BRIDGE_NAMESPACE, createEmbedBridge, parseInbound } from "./embedBridge";

describe("parseInbound", () => {
  it("accepts only versioned messages in the widget namespace", () => {
    expect(parseInbound({ ns: BRIDGE_NAMESPACE, v: 1, type: "open" })).toEqual({ type: "open" });
    expect(parseInbound({ ns: "other", v: 1, type: "open" })).toBeNull();
    expect(parseInbound({ ns: BRIDGE_NAMESPACE, v: 99, type: "open" })).toBeNull();
    expect(parseInbound("open")).toBeNull();
    expect(parseInbound({ ns: BRIDGE_NAMESPACE, v: 1, type: "steal" })).toBeNull();
  });

  it("validates payloads", () => {
    expect(
      parseInbound({ ns: BRIDGE_NAMESPACE, v: 1, type: "theme", payload: { scheme: "dark" } })
    ).toEqual({
      type: "theme",
      payload: { scheme: "dark" }
    });
    expect(
      parseInbound({ ns: BRIDGE_NAMESPACE, v: 1, type: "theme", payload: { scheme: "neon" } })
    ).toBeNull();
    expect(
      parseInbound({
        ns: BRIDGE_NAMESPACE,
        v: 1,
        type: "context",
        payload: { page_url: "https://a", page_title: 1 }
      })
    ).toEqual({ type: "context", payload: { page_url: "https://a", page_title: undefined } });
  });
});

describe("createEmbedBridge", () => {
  function setup(hostOrigin: string | null = "https://www.kommun.se") {
    const target = { postMessage: vi.fn() };
    let listener: ((event: MessageEvent) => void) | null = null;
    const handlers = { onOpen: vi.fn(), onTheme: vi.fn(), onContext: vi.fn() };
    const bridge = createEmbedBridge({
      hostOrigin,
      handlers,
      target,
      addListener: (l) => {
        listener = l;
        return () => {
          listener = null;
        };
      }
    });
    const dispatch = (origin: string, data: unknown, source: unknown = target) =>
      listener?.({ origin, data, source } as unknown as MessageEvent);
    return { bridge, target, handlers, dispatch, hasListener: () => listener !== null };
  }

  it("posts versioned envelopes to the host origin only", () => {
    const { bridge, target } = setup();
    const colors = {
      light: { accent: "#1F4E79", on_accent: "#FFFFFF" },
      dark: { accent: "#9CC7F0", on_accent: "#111111" }
    };
    bridge.ready();
    bridge.ready(colors);
    bridge.conversationStarted();
    bridge.ready(colors, "Fråga kommunen");
    bridge.ready(undefined, "Fråga kommunen");
    expect(target.postMessage).toHaveBeenNthCalledWith(
      1,
      { ns: BRIDGE_NAMESPACE, v: 1, type: "ready" },
      "https://www.kommun.se"
    );
    expect(target.postMessage).toHaveBeenNthCalledWith(
      2,
      { ns: BRIDGE_NAMESPACE, v: 1, type: "ready", payload: { colors } },
      "https://www.kommun.se"
    );
    expect(target.postMessage).toHaveBeenNthCalledWith(
      3,
      { ns: BRIDGE_NAMESPACE, v: 1, type: "conversation_started" },
      "https://www.kommun.se"
    );
    // The title names the loader's frame for screen readers.
    expect(target.postMessage).toHaveBeenNthCalledWith(
      4,
      { ns: BRIDGE_NAMESPACE, v: 1, type: "ready", payload: { colors, title: "Fråga kommunen" } },
      "https://www.kommun.se"
    );
    expect(target.postMessage).toHaveBeenNthCalledWith(
      5,
      { ns: BRIDGE_NAMESPACE, v: 1, type: "ready", payload: { title: "Fråga kommunen" } },
      "https://www.kommun.se"
    );
  });

  it("ignores messages from other origins or windows", () => {
    const { handlers, dispatch } = setup();
    dispatch("https://evil.example", { ns: BRIDGE_NAMESPACE, v: 1, type: "open" });
    dispatch(
      "https://www.kommun.se",
      { ns: BRIDGE_NAMESPACE, v: 1, type: "open" },
      { other: true }
    );
    expect(handlers.onOpen).not.toHaveBeenCalled();
    dispatch("https://www.kommun.se", { ns: BRIDGE_NAMESPACE, v: 1, type: "open" });
    expect(handlers.onOpen).toHaveBeenCalledTimes(1);
  });

  it("dispatches theme and context to handlers and can be destroyed", () => {
    const { bridge, handlers, dispatch, hasListener } = setup();
    dispatch("https://www.kommun.se", {
      ns: BRIDGE_NAMESPACE,
      v: 1,
      type: "theme",
      payload: { scheme: "light" }
    });
    dispatch("https://www.kommun.se", {
      ns: BRIDGE_NAMESPACE,
      v: 1,
      type: "context",
      payload: { page_url: "https://www.kommun.se/bygglov" }
    });
    expect(handlers.onTheme).toHaveBeenCalledWith("light");
    expect(handlers.onContext).toHaveBeenCalledWith({
      page_url: "https://www.kommun.se/bygglov",
      page_title: undefined
    });
    bridge.destroy();
    expect(hasListener()).toBe(false);
  });

  it("is inert without a host origin (stand-alone page)", () => {
    const { bridge, target } = setup(null);
    bridge.ready();
    expect(target.postMessage).not.toHaveBeenCalled();
  });
});
