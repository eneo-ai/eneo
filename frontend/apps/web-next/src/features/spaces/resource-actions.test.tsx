// @vitest-environment jsdom
import { act, cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { useRef, type ReactNode } from "react";
import { afterEach, beforeAll, describe, expect, it, vi } from "vitest";
import { renderInApp } from "@/test/render";
import { setViewport } from "@/test/setup-dom";
import type { Space } from "@/features/spaces/space";

const api = vi.hoisted(() => ({ POST: vi.fn(), DELETE: vi.fn(), GET: vi.fn() }));
const space = vi.hoisted(() => ({ current: null as unknown }));
vi.mock("@/lib/api/browser", () => ({ browserApi: api }));
vi.mock("@/lib/navigation", () => import("@/test/navigation"));
vi.mock("@/features/spaces/use-space", async () => {
  const { useSpaceFromQuery } = await import("@/features/spaces/testing/space-query");
  return { useSpace: () => useSpaceFromQuery(() => space.current as Space) };
});

import { ResourceCollection } from "@/components/composites/resource-tile";
import { AppActionScope } from "@/features/apps/actions";
import { AppTile } from "@/features/apps/tile";
import type { AppSparse } from "@/features/apps/apps";
import { ChatAppActionScope } from "@/features/assistants/actions";
import { ChatAppTile } from "@/features/assistants/tile";
import type { ChatAppItem } from "@/features/assistants/assistants";
import { ServiceActionScope } from "@/features/services/actions";
import { ServiceTile } from "@/features/services/tile";
import type { ServiceSparse } from "@/features/services/services";
import { makeAssistant, makeSpace } from "@/features/spaces/testing/space-fixture";
import { RemovalFocusScope } from "@/features/spaces/removal";

// Radix Select scrolls its selected option into view; jsdom has no layout.
beforeAll(() => {
  Element.prototype.scrollIntoView = () => {};
});
afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

const PERMISSIONS = ["read", "edit", "delete", "publish"];
const service = {
  id: "svc-1",
  name: "Kontrollerar avtal",
  permissions: PERMISSIONS
} as ServiceSparse;
const app = {
  id: "app-1",
  name: "Protokollsammanfattning",
  published: false,
  permissions: PERMISSIONS
} as AppSparse;
const assistant = makeAssistant({ id: "as-1", name: "Upphandlingsassistenten" }) as ChatAppItem;
const groupChat = {
  id: "gc-1",
  type: "group-chat",
  name: "Samrådsgruppen",
  published: false,
  permissions: PERMISSIONS
} as unknown as ChatAppItem;

function Page({
  scope: Scope,
  children
}: {
  scope: (props: {
    focusTarget: React.RefObject<HTMLElement | null>;
    children: ReactNode;
  }) => ReactNode;
  children: ReactNode;
}) {
  const heading = useRef<HTMLHeadingElement>(null);
  return (
    <RemovalFocusScope target={heading}>
      <Scope focusTarget={heading}>
        <h2 ref={heading} tabIndex={-1}>
          Resurser
        </h2>
        <ResourceCollection>{children}</ResourceCollection>
      </Scope>
    </RemovalFocusScope>
  );
}

function choose(name: string, item: string) {
  const trigger = screen.getByRole("button", { name: `Fler åtgärder för ${name}` });
  fireEvent.click(trigger);
  const menu = document.getElementById(trigger.getAttribute("aria-controls")!)!;
  fireEvent.click(within(menu).getByRole("menuitem", { name: item }));
}

const openDialog = () =>
  document.querySelector<HTMLElement>('dialog[open], [role="alertdialog"], [role="dialog"]');

describe("a resource's menu dialog when a turned phone swaps rows for cards", () => {
  it("keeps a service's move dialog open", async () => {
    space.current = makeSpace({ services: [service] });
    setViewport("phone");
    renderInApp(
      <Page scope={ServiceActionScope}>
        <ServiceTile service={service} />
      </Page>
    );
    choose("Kontrollerar avtal", "Flytta");
    await waitFor(() => expect(openDialog()).not.toBeNull());
    const dialog = openDialog();

    act(() => setViewport("tablet-portrait"));
    expect(openDialog()).toBe(dialog);
    act(() => setViewport("phone"));
    expect(openDialog()).toBe(dialog);
  });

  it("keeps the destination chosen in a service's move dialog across a turn in both directions", async () => {
    space.current = makeSpace({ services: [service] });
    // The spaces the service can be moved to (this space itself is left out of the list).
    api.GET.mockImplementation((path: string) =>
      Promise.resolve({
        data:
          path === "/api/v1/spaces/"
            ? {
                items: [
                  { id: "space-1", name: "Den här ytan" },
                  { id: "space-9", name: "Upphandling Norr" }
                ]
              }
            : {},
        response: new Response("{}")
      })
    );
    api.POST.mockResolvedValue({ data: {}, response: new Response("{}") });
    setViewport("phone");
    renderInApp(
      <Page scope={ServiceActionScope}>
        <ServiceTile service={service} />
      </Page>
    );
    choose("Kontrollerar avtal", "Flytta");
    await waitFor(() => expect(openDialog()).not.toBeNull());
    const dialog = openDialog()!;

    const picker = within(dialog).getByRole("combobox", { name: "Destination" });
    fireEvent.click(picker);
    fireEvent.click(await screen.findByRole("option", { name: "Upphandling Norr" }));
    expect(within(dialog).getByRole("combobox", { name: "Destination" }).textContent).toContain(
      "Upphandling Norr"
    );

    // Turned both ways: the same dialog, with the destination still chosen.
    act(() => setViewport("tablet-portrait"));
    expect(openDialog()).toBe(dialog);
    expect(within(dialog).getByRole("combobox", { name: "Destination" }).textContent).toContain(
      "Upphandling Norr"
    );
    act(() => setViewport("phone"));
    expect(openDialog()).toBe(dialog);
    expect(within(dialog).getByRole("combobox", { name: "Destination" }).textContent).toContain(
      "Upphandling Norr"
    );

    // And it moves to the destination that was chosen before the turn.
    fireEvent.click(within(dialog).getByRole("button", { name: "Flytta tjänst" }));
    await waitFor(() => expect(api.POST).toHaveBeenCalledTimes(1));
    expect(api.POST.mock.calls[0]![1]).toEqual({
      params: { path: { id: "svc-1" } },
      body: { target_space_id: "space-9" }
    });
  });

  it("still deletes the service from the dialog it opened on a phone", async () => {
    space.current = makeSpace({ services: [service] });
    api.DELETE.mockResolvedValue({ data: {}, response: new Response("{}") });
    setViewport("phone");
    renderInApp(
      <Page scope={ServiceActionScope}>
        <ServiceTile service={service} />
      </Page>
    );
    choose("Kontrollerar avtal", "Ta bort");
    await waitFor(() => expect(openDialog()).not.toBeNull());
    const dialog = openDialog()!;

    act(() => setViewport("tablet-portrait"));
    expect(openDialog()).toBe(dialog);
    fireEvent.click(within(dialog).getByRole("button", { name: "Ta bort" }));

    await waitFor(() => expect(api.DELETE).toHaveBeenCalledTimes(1));
    expect(api.DELETE.mock.calls[0]![1]).toEqual({ params: { path: { id: "svc-1" } } });
    await waitFor(() => expect(openDialog()).toBeNull());
  });

  it("keeps an app's publish dialog open", async () => {
    space.current = makeSpace({ apps: [app] });
    setViewport("tablet-portrait");
    renderInApp(
      <Page scope={AppActionScope}>
        <AppTile app={app} showStatus />
      </Page>
    );
    choose("Protokollsammanfattning", "Publicera");
    await waitFor(() => expect(openDialog()).not.toBeNull());
    const dialog = openDialog();

    act(() => setViewport("phone"));
    expect(openDialog()).toBe(dialog);
  });

  it("keeps an assistant's move dialog and a group chat's delete dialog open", async () => {
    space.current = makeSpace({ assistants: [assistant], groupChats: [groupChat] });
    setViewport("phone");
    renderInApp(
      <Page scope={ChatAppActionScope}>
        <ChatAppTile item={assistant} showStatus />
        <ChatAppTile item={groupChat} showStatus />
      </Page>
    );

    choose("Upphandlingsassistenten", "Flytta");
    await waitFor(() => expect(openDialog()).not.toBeNull());
    const move = openDialog();
    act(() => setViewport("tablet-portrait"));
    expect(openDialog()).toBe(move);
    fireEvent.click(within(move!).getByRole("button", { name: "Avbryt" }));
    await waitFor(() => expect(openDialog()).toBeNull());

    choose("Samrådsgruppen", "Ta bort");
    await waitFor(() => expect(openDialog()).not.toBeNull());
    const remove = openDialog();
    act(() => setViewport("phone"));
    expect(openDialog()).toBe(remove);
  });
});
