import { describe, expect, it } from "vitest";
import {
  conversationHref,
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

  it("selects the conversation for a saved personal chat", () => {
    expect(navTarget("/spaces/personal/chat", params("session_id=s-1"))).toEqual({
      kind: "conversation",
      sessionId: "s-1"
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

it("builds conversation links in the personal chat's URL scheme", () => {
  expect(conversationHref("s 1")).toBe("/spaces/personal/chat?session_id=s+1");
});
