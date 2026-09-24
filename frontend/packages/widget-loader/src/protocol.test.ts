import { describe, expect, it } from "vitest";
import { BRIDGE_NAMESPACE, BRIDGE_VERSION, envelope, parseFrameMessage } from "./protocol";

describe("parseFrameMessage", () => {
  it("accepts every message the embed page sends", () => {
    expect(parseFrameMessage({ ns: BRIDGE_NAMESPACE, v: 1, type: "ready" })).toEqual({
      type: "ready"
    });
    const colors = {
      light: { accent: "#1F4E79", on_accent: "#FFFFFF" },
      dark: { accent: "#9CC7F0", on_accent: "#111111" }
    };
    expect(
      parseFrameMessage({ ns: BRIDGE_NAMESPACE, v: 1, type: "ready", payload: { colors } })
    ).toEqual({ type: "ready", payload: { colors } });
    expect(
      parseFrameMessage({
        ns: BRIDGE_NAMESPACE,
        v: 1,
        type: "ready",
        payload: { colors, title: "  Fråga kommunen " }
      })
    ).toEqual({ type: "ready", payload: { colors, title: "Fråga kommunen" } });
    expect(parseFrameMessage({ ns: BRIDGE_NAMESPACE, v: 1, type: "close" })).toEqual({
      type: "close"
    });
    // Whatever an embed page sends along, the host never gets an identifier.
    expect(
      parseFrameMessage({
        ns: BRIDGE_NAMESPACE,
        v: 1,
        type: "conversation_started",
        payload: { session_id: "abc" }
      })
    ).toEqual({ type: "conversation_started" });
    expect(
      parseFrameMessage({ ns: BRIDGE_NAMESPACE, v: 1, type: "unread", payload: { count: 2.7 } })
    ).toEqual({ type: "unread", payload: { count: 2 } });
  });

  it("rejects foreign, newer or malformed messages", () => {
    expect(parseFrameMessage(null)).toBeNull();
    expect(parseFrameMessage("ready")).toBeNull();
    expect(
      parseFrameMessage({
        ns: BRIDGE_NAMESPACE,
        v: 1,
        type: "ready",
        payload: { colors: { light: { accent: "red", on_accent: "#fff" } } }
      })
    ).toEqual({ type: "ready" });
    // A title must be text; a blank one is no title, a long one is cut.
    expect(
      parseFrameMessage({ ns: BRIDGE_NAMESPACE, v: 1, type: "ready", payload: { title: 42 } })
    ).toEqual({ type: "ready" });
    expect(
      parseFrameMessage({ ns: BRIDGE_NAMESPACE, v: 1, type: "ready", payload: { title: "  " } })
    ).toEqual({ type: "ready" });
    expect(
      parseFrameMessage({
        ns: BRIDGE_NAMESPACE,
        v: 1,
        type: "ready",
        payload: { title: "x".repeat(300) }
      })
    ).toEqual({ type: "ready", payload: { title: "x".repeat(200) } });
    expect(parseFrameMessage({ ns: "other", v: 1, type: "ready" })).toBeNull();
    expect(
      parseFrameMessage({ ns: BRIDGE_NAMESPACE, v: BRIDGE_VERSION + 1, type: "ready" })
    ).toBeNull();
    expect(parseFrameMessage({ ns: BRIDGE_NAMESPACE, v: 1, type: "resize" })).toBeNull();
    expect(
      parseFrameMessage({ ns: BRIDGE_NAMESPACE, v: 1, type: "unread", payload: {} })
    ).toBeNull();
    expect(
      parseFrameMessage({ ns: BRIDGE_NAMESPACE, v: 1, type: "unread", payload: { count: -1 } })
    ).toBeNull();
  });

  it("stamps outbound messages with namespace and version", () => {
    expect(envelope({ type: "open" })).toEqual({
      ns: BRIDGE_NAMESPACE,
      v: BRIDGE_VERSION,
      type: "open"
    });
  });
});
