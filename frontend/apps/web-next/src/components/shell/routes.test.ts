import { describe, expect, it } from "vitest";
import {
  conversationHref,
  currentNavTarget,
  isAdminRoute,
  isChatRoute,
  navTarget,
  spaceRouteIdFromPath
} from "./routes";

describe("isChatRoute", () => {
  it("matches the chat routes that render their own mobile header", () => {
    expect(isChatRoute("/spaces/personal/chat")).toBe(true);
    expect(isChatRoute("/spaces/7f0c/chat")).toBe(true);
    expect(isChatRoute("/dashboard/assistant-1")).toBe(true);
    expect(isChatRoute("/dashboard/assistant-1/session-9")).toBe(true);
  });

  it("leaves every other page to the shell's top bar", () => {
    expect(isChatRoute("/dashboard")).toBe(false);
    expect(isChatRoute("/dashboard/app/app-1")).toBe(false);
    expect(isChatRoute("/dashboard/app/app-1/results/run-1")).toBe(false);
    expect(isChatRoute("/spaces/list")).toBe(false);
    expect(isChatRoute("/spaces/7f0c/overview")).toBe(false);
    expect(isChatRoute("/spaces/7f0c/knowledge")).toBe(false);
    expect(isChatRoute("/admin/models")).toBe(false);
    expect(isChatRoute("/account")).toBe(false);
    expect(isChatRoute("/")).toBe(false);
  });
});

describe("isAdminRoute", () => {
  it("is true for /admin and below only", () => {
    expect(isAdminRoute("/admin")).toBe(true);
    expect(isAdminRoute("/admin/models")).toBe(true);
    expect(isAdminRoute("/administration")).toBe(false);
    expect(isAdminRoute("/spaces/admin/overview")).toBe(false);
  });
});

describe("spaceRouteIdFromPath", () => {
  it("reads the space segment of space pages", () => {
    expect(spaceRouteIdFromPath("/spaces/personal/chat")).toBe("personal");
    expect(spaceRouteIdFromPath("/spaces/abc/knowledge/collections/1")).toBe("abc");
    expect(spaceRouteIdFromPath("/spaces/list")).toBeNull();
    expect(spaceRouteIdFromPath("/dashboard")).toBeNull();
  });
});

describe("navTarget", () => {
  const params = (query = "") => new URLSearchParams(query);

  it("selects Ny konversation for a fresh personal chat", () => {
    expect(navTarget("/spaces/personal/chat", params())).toEqual({ kind: "new-conversation" });
  });

  it("selects the conversation for a saved personal chat, with no place behind it", () => {
    expect(navTarget("/spaces/personal/chat", params("session_id=s-1"))).toEqual({
      kind: "conversation",
      sessionId: "s-1",
      otherwise: { kind: "none" }
    });
  });

  it("selects the conversation for a saved chat in any space, its space behind it", () => {
    expect(navTarget("/spaces/abc/chat", params("type=assistant&id=a-1&session_id=s-1"))).toEqual({
      kind: "conversation",
      sessionId: "s-1",
      otherwise: { kind: "space", routeId: "abc" }
    });
    expect(navTarget("/spaces/abc/chat", params("session_id=s-2"))).toEqual({
      kind: "conversation",
      sessionId: "s-2",
      otherwise: { kind: "space", routeId: "abc" }
    });
    expect(
      navTarget("/spaces/personal/chat", params("type=group-chat&id=g-1&session_id=s-3"))
    ).toEqual({
      kind: "conversation",
      sessionId: "s-3",
      otherwise: { kind: "space", routeId: "personal" }
    });
    expect(navTarget("/spaces/organization/chat", params("session_id=s-4"))).toEqual({
      kind: "conversation",
      sessionId: "s-4",
      otherwise: { kind: "organization" }
    });
  });

  it("selects the space for other partners and pages of a space", () => {
    expect(navTarget("/spaces/personal/chat", params("type=assistant&id=a-1"))).toEqual({
      kind: "space",
      routeId: "personal"
    });
    expect(navTarget("/spaces/personal/knowledge", params())).toEqual({
      kind: "space",
      routeId: "personal"
    });
    expect(navTarget("/spaces/abc/chat", params())).toEqual({ kind: "space", routeId: "abc" });
  });

  it("maps the list, organisation and assistant catalog", () => {
    expect(navTarget("/spaces/list", params())).toEqual({ kind: "all-spaces" });
    expect(navTarget("/spaces/organization/knowledge", params())).toEqual({
      kind: "organization"
    });
    expect(navTarget("/dashboard", params())).toEqual({ kind: "assistants" });
    expect(navTarget("/dashboard/a-1", params())).toEqual({ kind: "assistants" });
    expect(navTarget("/account", params())).toEqual({ kind: "none" });
  });
});

describe("currentNavTarget", () => {
  const saved = navTarget("/spaces/abc/chat", new URLSearchParams("session_id=s-1"));

  it("keeps a conversation that Senaste lists", () => {
    expect(currentNavTarget(saved, ["s-0", "s-1"])).toBe(saved);
  });

  it("falls back to its place when Senaste doesn't list it", () => {
    expect(currentNavTarget(saved, ["s-0"])).toEqual({ kind: "space", routeId: "abc" });
    const personal = navTarget("/spaces/personal/chat", new URLSearchParams("session_id=s-1"));
    expect(currentNavTarget(personal, [])).toEqual({ kind: "none" });
  });

  it("leaves every other destination alone", () => {
    const space = navTarget("/spaces/abc/overview", null);
    expect(currentNavTarget(space, [])).toBe(space);
  });
});

describe("conversationHref", () => {
  const space = { id: "abc", personal: false, organization: false };
  const personal = { id: "p-1", personal: true, organization: false };

  it("opens the personal chat in its own URL scheme", () => {
    expect(
      conversationHref({
        id: "s 1",
        partner: { type: "default-assistant", id: "d-1" },
        space: personal
      })
    ).toBe("/spaces/personal/chat?session_id=s+1");
  });

  it("opens other partners in their space's chat, as the chat builds the URL itself", () => {
    expect(conversationHref({ id: "s-1", partner: { type: "assistant", id: "a-1" }, space })).toBe(
      "/spaces/abc/chat?type=assistant&id=a-1&session_id=s-1"
    );
    expect(
      conversationHref({ id: "s-2", partner: { type: "group-chat", id: "g-1" }, space: personal })
    ).toBe("/spaces/personal/chat?type=group-chat&id=g-1&session_id=s-2");
    expect(
      conversationHref({ id: "s-3", partner: { type: "default-assistant", id: "d-2" }, space })
    ).toBe("/spaces/abc/chat?session_id=s-3");
    expect(
      conversationHref({
        id: "s-4",
        partner: { type: "assistant", id: "a-2" },
        space: { id: "org", personal: false, organization: true }
      })
    ).toBe("/spaces/organization/chat?type=assistant&id=a-2&session_id=s-4");
  });

  it("round-trips to the conversation in navTarget", () => {
    const href = conversationHref({ id: "s-1", partner: { type: "assistant", id: "a-1" }, space });
    const url = new URL(href, "https://eneo.example");
    expect(navTarget(url.pathname, url.searchParams)).toMatchObject({
      kind: "conversation",
      sessionId: "s-1"
    });
  });
});
