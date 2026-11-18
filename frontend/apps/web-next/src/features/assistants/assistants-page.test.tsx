// @vitest-environment jsdom
import { act, cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { openMenuOnRelease, tap } from "@/test/menus";
import { renderInApp } from "@/test/render";
import { setViewport } from "@/test/setup-dom";
import {
  spaceHasPermission,
  type ResourcePermission,
  type Space,
  type SpaceResource
} from "@/features/spaces/space";
import { makeSpace } from "@/features/spaces/testing/space-fixture";
import { AssistantsPage } from "./assistants-page";

const state = vi.hoisted(() => ({ space: null as unknown }));

vi.mock("@/lib/navigation", () => import("@/test/navigation"));
vi.mock("@/features/spaces/use-space", () => ({
  useSpace: () => ({
    space: state.space,
    routeId: "space-1",
    can: (action: ResourcePermission, resource: SpaceResource) =>
      spaceHasPermission(state.space as Space, action, resource)
  })
}));
vi.mock("@/lib/api/browser", () => ({ browserApi: {} }));

afterEach(cleanup);

const assistants = (count: number) =>
  Array.from({ length: count }, (_, index) => ({
    id: `assistant-${index}`,
    name: `Assistent ${index + 1}`,
    description: null,
    published: true,
    permissions: ["read"],
    completion_model: null,
    updated_at: "2026-09-10T08:00:00Z"
  }));

function show(count: number) {
  state.space = makeSpace({ assistants: assistants(count) });
  return renderInApp(<AssistantsPage />);
}

describe("AssistantsPage on a phone", () => {
  it("names itself for screen readers only, and keeps focus on the visible page", () => {
    setViewport("phone");
    const { container } = show(3);
    // The space's active tab above says "Assistenter": the title is not drawn again.
    const title = screen.getByRole("heading", { level: 2, name: "Assistenter" });
    expect(title.closest(".phone\\:sr-only")).toBeTruthy();
    // What a removal or an action needs to focus is the page, not the clipped title.
    const page = container.querySelector<HTMLElement>("div.flex.w-full.flex-col[tabindex='-1']");
    expect(page).toBeTruthy();
    expect(page!.contains(title)).toBe(true);
    expect(page!.className).toContain("focus-visible:outline-2");
  });
});

describe("AssistantsPage filter", () => {
  it("is left out on a phone while there are few assistants, and comes with many", () => {
    setViewport("phone");
    show(3);
    expect(screen.queryByRole("textbox", { name: /Filtrera/ })).toBeNull();
    cleanup();
    show(7);
    expect(screen.getByRole("textbox", { name: /Filtrera/ })).toBeTruthy();
  });

  it("stops filtering when the field goes (a turned screen), so nothing is left hidden for good", () => {
    setViewport("tablet-portrait");
    show(3);
    fireEvent.change(screen.getByRole("textbox", { name: /Filtrera/ }), {
      target: { value: "Assistent 1" }
    });
    expect(screen.queryByText("Assistent 2")).toBeNull();

    act(() => setViewport("phone"));
    expect(screen.queryByRole("textbox", { name: /Filtrera/ })).toBeNull();
    expect(screen.getByText("Assistent 2")).toBeTruthy();
  });

  it("drops a chosen sort when its control goes (a turned screen), so no order is left stuck", async () => {
    setViewport("tablet-portrait");
    show(3);
    const names = () => screen.getAllByText(/^Assistent \d$/).map((name) => name.textContent);
    const menu = await openMenuOnRelease(screen.getByRole("button", { name: /^Sortera/ }));
    tap(within(menu).getByRole("menuitemradio", { name: /^Namn · Fallande/ }));
    await waitFor(() => expect(names()[0]).toBe("Assistent 3"));

    act(() => setViewport("phone"));
    expect(names()[0]).toBe("Assistent 1");
  });

  it("is always there from a tablet up", () => {
    setViewport("tablet-portrait");
    show(3);
    expect(screen.getByRole("textbox", { name: /Filtrera/ })).toBeTruthy();
  });
});
