// @vitest-environment jsdom
import { cleanup, fireEvent, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { expectNoAxeViolations } from "@/test/axe";
import { renderInApp } from "@/test/render";
import {
  spaceHasPermission,
  type ResourcePermission,
  type Space,
  type SpaceResource
} from "./space";
import { makeAssistant, makeSpace } from "./testing/space-fixture";

const state = vi.hoisted(() => ({ space: null as unknown }));

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: () => {}, prefetch: () => {} })
}));
vi.mock("@/features/spaces/use-space", () => ({
  useSpace: () => ({
    space: state.space,
    routeId: "space-1",
    can: (action: ResourcePermission, resource: SpaceResource) =>
      spaceHasPermission(state.space as Space, action, resource)
  })
}));
vi.mock("@/lib/api/browser", () => ({
  browserApi: {
    GET: () => Promise.resolve({ data: { items: [] }, response: new Response("{}") })
  }
}));
vi.mock("@/components/providers/app-context", () => ({
  useAppContext: () => ({
    can: () => true,
    settings: { using_templates: false },
    limits: { attachments: { formats: [] } },
    user: { id: "user-1" }
  })
}));

import { AppsPage } from "@/features/apps/apps-page";
import { AssistantsPage } from "@/features/assistants/assistants-page";
import { ServicesPage } from "@/features/services/services-page";

afterEach(cleanup);

function show(space: Space, page: React.ReactNode) {
  state.space = space;
  return renderInApp(page);
}

const assistants = [
  makeAssistant(),
  makeAssistant({ id: "a2", name: "Avtalsgranskaren", published: false, description: null })
];

describe("AssistantsPage", () => {
  it("groups cards by status for publishers, each card a link to its chat", async () => {
    const { container } = show(makeSpace({ assistants }), <AssistantsPage />);

    expect(screen.getByRole("heading", { level: 2, name: "Assistenter" })).toBeTruthy();
    expect(screen.getAllByRole("button", { name: "Skapa assistent" })).toHaveLength(1);
    const published = screen.getByRole("region", { name: "Publicerad" });
    const card = within(published).getByRole("link", { name: "Upphandlingsassistenten" });
    expect(card.getAttribute("href")).toBe("/spaces/space-1/chat?type=assistant&id=assistant-1");
    expect(within(published).getByText("Svarar på frågor om LOU.")).toBeTruthy();
    expect(within(published).getByText("Haiku 4.5")).toBeTruthy();
    expect(
      within(screen.getByRole("region", { name: "Utkast" })).getByRole("link", {
        name: "Avtalsgranskaren"
      })
    ).toBeTruthy();
    await expectNoAxeViolations(container);

    fireEvent.change(screen.getByRole("textbox", { name: "Sök" }), { target: { value: "avtal" } });
    expect(screen.queryByRole("link", { name: "Upphandlingsassistenten" })).toBeNull();
  });

  it("shows the status on each card for users who cannot publish", () => {
    show(
      makeSpace({ assistants, resourcePermissions: ["read", "create", "edit", "delete"] }),
      <AssistantsPage />
    );
    const cards = within(screen.getAllByRole("list")[0]!).getAllByRole("link");
    expect(cards.map((link) => link.getAttribute("aria-label"))).toEqual([
      "Avtalsgranskaren",
      "Upphandlingsassistenten"
    ]);
    expect(screen.getByText("Utkast")).toBeTruthy();
    expect(screen.getByText("Publicerad")).toBeTruthy();
  });

  it("puts the create menu in the empty state", async () => {
    const { container } = show(makeSpace(), <AssistantsPage />);
    expect(screen.getByRole("heading", { name: "Inga assistenter ännu" })).toBeTruthy();
    expect(screen.getAllByRole("button", { name: "Skapa assistent" })).toHaveLength(1);
    await expectNoAxeViolations(container);
  });
});

describe("AppsPage and ServicesPage", () => {
  it("render the same card grid", async () => {
    const space = makeSpace({
      apps: [
        {
          id: "app-1",
          name: "Protokollsammanfattning",
          description: "Sammanfattar protokoll.",
          published: true,
          user_id: "u",
          permissions: ["read", "edit", "delete"]
        }
      ],
      services: [
        {
          id: "service-1",
          name: "Klassificering",
          prompt: "…",
          output_format: "json",
          user_id: "u",
          permissions: ["read", "edit", "delete"]
        }
      ]
    });

    const apps = show(space, <AppsPage />);
    expect(screen.getByRole("link", { name: "Protokollsammanfattning" }).getAttribute("href")).toBe(
      "/spaces/space-1/apps/app-1"
    );
    expect(screen.getByText("Sammanfattar protokoll.")).toBeTruthy();
    await expectNoAxeViolations(apps.container);
    cleanup();

    const services = show(space, <ServicesPage />);
    expect(screen.getByRole("link", { name: "Klassificering" }).getAttribute("href")).toBe(
      "/spaces/space-1/services/service-1?tab=playground"
    );
    expect(screen.getByText("JSON")).toBeTruthy();
    await expectNoAxeViolations(services.container);
  });

  it("explain empty lists and offer the create action", () => {
    show(makeSpace(), <ServicesPage />);
    expect(screen.getByRole("heading", { name: "Inga tjänster ännu" })).toBeTruthy();
    expect(screen.getAllByRole("button", { name: "Skapa tjänst" })).toHaveLength(1);
  });
});
