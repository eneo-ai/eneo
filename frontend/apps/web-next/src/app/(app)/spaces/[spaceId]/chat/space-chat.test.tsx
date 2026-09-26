// @vitest-environment jsdom
import { cleanup, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { renderInApp } from "@/test/render";
import { SpaceChat } from "./space-chat.client";

const route = vi.hoisted(() => ({
  space: {
    id: "space-1",
    name: "Upphandling",
    personal: false,
    organization: false,
    security_classification: null,
    default_assistant: null as unknown,
    completion_models: []
  }
}));
const api = vi.hoisted(() => ({
  GET: vi.fn(async () => ({
    data: undefined,
    error: { message: "Forbidden" },
    response: new Response(null, { status: 403 })
  }))
}));

vi.mock("next/navigation", () => import("@/test/navigation"));
vi.mock("@/features/spaces/use-space", () => ({
  useSpace: () => ({ space: route.space, routeId: "space-1", can: () => true })
}));
vi.mock("@/lib/api/browser", () => ({ browserApi: api }));

afterEach(() => {
  cleanup();
  api.GET.mockClear();
});

function renderRoute(url = "/spaces/space-1/chat") {
  return renderInApp(<SpaceChat />, { route: url });
}

describe("SpaceChat", () => {
  it("offers a retry when an assistant in the space can't be loaded", async () => {
    renderRoute("/spaces/space-1/chat?type=assistant&id=assistant-9");
    expect(await screen.findByText("Det gick inte att öppna chatten")).toBeTruthy();
    expect(screen.getByRole("button", { name: "Försök igen" })).toBeTruthy();
  });

  it("says so without a retry when the space has no assistant to chat with", () => {
    renderRoute();
    expect(screen.getByText("Det gick inte att öppna chatten")).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Försök igen" })).toBeNull();
    expect(api.GET).not.toHaveBeenCalled();
  });
});
