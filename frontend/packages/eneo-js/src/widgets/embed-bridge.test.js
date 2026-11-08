import assert from "node:assert/strict";
import { describe, it, mock } from "node:test";
import { BRIDGE_NAMESPACE, createEmbedBridge, parseInbound } from "./embed-bridge.js";
describe("parseInbound", () => {
  it("accepts only versioned messages in the widget namespace", () => {
    assert.deepStrictEqual(parseInbound({ ns: BRIDGE_NAMESPACE, v: 1, type: "open" }), {
      type: "open"
    });
    assert.strictEqual(parseInbound({ ns: "other", v: 1, type: "open" }), null);
    assert.strictEqual(parseInbound({ ns: BRIDGE_NAMESPACE, v: 99, type: "open" }), null);
    assert.strictEqual(parseInbound("open"), null);
    assert.strictEqual(parseInbound({ ns: BRIDGE_NAMESPACE, v: 1, type: "steal" }), null);
  });
  it("validates payloads", () => {
    assert.deepStrictEqual(
      parseInbound({ ns: BRIDGE_NAMESPACE, v: 1, type: "theme", payload: { scheme: "dark" } }),
      {
        type: "theme",
        payload: { scheme: "dark" }
      }
    );
    assert.strictEqual(
      parseInbound({ ns: BRIDGE_NAMESPACE, v: 1, type: "theme", payload: { scheme: "neon" } }),
      null
    );
    assert.deepStrictEqual(
      parseInbound({
        ns: BRIDGE_NAMESPACE,
        v: 1,
        type: "context",
        payload: { page_url: "https://a", page_title: 1 }
      }),
      { type: "context", payload: { page_url: "https://a", page_title: undefined } }
    );
    assert.deepStrictEqual(
      parseInbound({
        ns: BRIDGE_NAMESPACE,
        v: 1,
        type: "layout",
        payload: { full: true, expanded: false, extra: 1 }
      }),
      { type: "layout", payload: { full: true, expanded: false } }
    );
    // Both flags must be real booleans; a half layout is no layout.
    assert.strictEqual(
      parseInbound({ ns: BRIDGE_NAMESPACE, v: 1, type: "layout", payload: { full: "yes" } }),
      null
    );
    assert.strictEqual(parseInbound({ ns: BRIDGE_NAMESPACE, v: 1, type: "layout" }), null);
  });
});
describe("createEmbedBridge", () => {
  function setup(hostOrigin = "https://www.kommun.se") {
    const target = { postMessage: mock.fn() };
    let listener = null;
    const handlers = {
      onOpen: mock.fn(),
      onTheme: mock.fn(),
      onContext: mock.fn(),
      onLayout: mock.fn()
    };
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
    const dispatch = (origin, data, source = target) => listener?.({ origin, data, source });
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
    assert.deepStrictEqual(target.postMessage.mock.calls[0].arguments, [
      { ns: BRIDGE_NAMESPACE, v: 1, type: "ready" },
      "https://www.kommun.se"
    ]);
    assert.deepStrictEqual(target.postMessage.mock.calls[1].arguments, [
      { ns: BRIDGE_NAMESPACE, v: 1, type: "ready", payload: { colors } },
      "https://www.kommun.se"
    ]);
    assert.deepStrictEqual(target.postMessage.mock.calls[2].arguments, [
      { ns: BRIDGE_NAMESPACE, v: 1, type: "conversation_started" },
      "https://www.kommun.se"
    ]);
    // The title names the loader's frame for screen readers.
    assert.deepStrictEqual(target.postMessage.mock.calls[3].arguments, [
      { ns: BRIDGE_NAMESPACE, v: 1, type: "ready", payload: { colors, title: "Fråga kommunen" } },
      "https://www.kommun.se"
    ]);
    assert.deepStrictEqual(target.postMessage.mock.calls[4].arguments, [
      { ns: BRIDGE_NAMESPACE, v: 1, type: "ready", payload: { title: "Fråga kommunen" } },
      "https://www.kommun.se"
    ]);
  });
  it("ignores messages from other origins or windows", () => {
    const { handlers, dispatch } = setup();
    dispatch("https://evil.example", { ns: BRIDGE_NAMESPACE, v: 1, type: "open" });
    dispatch(
      "https://www.kommun.se",
      { ns: BRIDGE_NAMESPACE, v: 1, type: "open" },
      { other: true }
    );
    assert.equal(handlers.onOpen.mock.callCount(), 0);
    dispatch("https://www.kommun.se", { ns: BRIDGE_NAMESPACE, v: 1, type: "open" });
    assert.equal(handlers.onOpen.mock.callCount(), 1);
  });
  it("asks the loader to expand and to collapse the panel", () => {
    const { bridge, target } = setup();
    bridge.expand();
    bridge.collapse();
    assert.deepStrictEqual(target.postMessage.mock.calls[0].arguments, [
      { ns: BRIDGE_NAMESPACE, v: 1, type: "expand" },
      "https://www.kommun.se"
    ]);
    assert.deepStrictEqual(target.postMessage.mock.calls[1].arguments, [
      { ns: BRIDGE_NAMESPACE, v: 1, type: "collapse" },
      "https://www.kommun.se"
    ]);
  });
  it("dispatches theme, context and layout to handlers and can be destroyed", () => {
    const { bridge, handlers, dispatch, hasListener } = setup();
    dispatch("https://www.kommun.se", {
      ns: BRIDGE_NAMESPACE,
      v: 1,
      type: "layout",
      payload: { full: false, expanded: false }
    });
    assert.deepEqual(
      handlers.onLayout.mock.calls.map((call) => call.arguments),
      [[{ full: false, expanded: false }]]
    );
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
    assert.deepEqual(
      handlers.onTheme.mock.calls.map((call) => call.arguments),
      [["light"]]
    );
    assert.deepEqual(
      handlers.onContext.mock.calls.map((call) => call.arguments),
      [
        [
          {
            page_url: "https://www.kommun.se/bygglov",
            page_title: undefined
          }
        ]
      ]
    );
    bridge.destroy();
    assert.deepStrictEqual(hasListener(), false);
  });
  it("is inert without a host origin (stand-alone page)", () => {
    const { bridge, target } = setup(null);
    bridge.ready();
    assert.equal(target.postMessage.mock.callCount(), 0);
  });
});
