import { describe, expect, it } from "vitest";
import { BRIDGE_NAMESPACE, BRIDGE_VERSION, envelope, parseFrameMessage } from "./protocol";

describe("parseFrameMessage", () => {
  it("accepts every message the embed page sends", () => {
    expect(parseFrameMessage({ ns: BRIDGE_NAMESPACE, v: 1, type: "ready" })).toEqual({
      type: "ready"
    });
    expect(parseFrameMessage({ ns: BRIDGE_NAMESPACE, v: 1, type: "close" })).toEqual({
      type: "close"
    });
    expect(
      parseFrameMessage({
        ns: BRIDGE_NAMESPACE,
        v: 1,
        type: "conversation_started",
        payload: { session_id: "abc" }
      })
    ).toEqual({ type: "conversation_started", payload: { session_id: "abc" } });
    expect(
      parseFrameMessage({ ns: BRIDGE_NAMESPACE, v: 1, type: "unread", payload: { count: 2.7 } })
    ).toEqual({ type: "unread", payload: { count: 2 } });
  });

  it("rejects foreign, newer or malformed messages", () => {
    expect(parseFrameMessage(null)).toBeNull();
    expect(parseFrameMessage("ready")).toBeNull();
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
    expect(
      parseFrameMessage({ ns: BRIDGE_NAMESPACE, v: 1, type: "conversation_started", payload: {} })
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
