// @vitest-environment jsdom
import { cleanup, fireEvent, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { expectNoAxeViolations } from "@/test/axe";
import { router } from "@/test/navigation";
import { renderInApp, testAppContext } from "@/test/render";
import {
  spaceHasPermission,
  type ResourcePermission,
  type Space,
  type SpaceResource
} from "../space";
import {
  makeAssistant,
  makeCollection,
  makeMember,
  makeSpace,
  makeWebsite
} from "../testing/space-fixture";

const state = vi.hoisted(() => ({ space: null as unknown }));

vi.mock("next/navigation", () => import("@/test/navigation"));
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
vi.mock("@/features/jobs/use-jobs", () => ({
  useJobs: () => ({ trackJob: () => {}, queueUploads: () => {} })
}));

import { SpaceOverview } from "@/app/(app)/spaces/[spaceId]/overview/space-overview.client";

afterEach(cleanup);

const appContext = testAppContext({
  permissions: ["admin"],
  settings: { using_templates: true },
  limits: {
    attachments: { formats: [] },
    info_blobs: {
      formats: [
        { mimetype: "application/pdf", extensions: ["pdf"], size: 10_000_000, vision: false }
      ]
    }
  }
});

function show(space: Space) {
  state.space = space;
  return renderInApp(<SpaceOverview />, { appContext });
}

const busySpace = () =>
  makeSpace({
    assistants: [
      makeAssistant(),
      makeAssistant({
        id: "a2",
        name: "Avtalsgranskaren",
        published: false,
        completion_model_id: "model-2",
        updated_at: "2026-09-05T08:00:00Z"
      }),
      makeAssistant({ id: "a3", name: "Äldst", updated_at: "2025-01-01T00:00:00Z" })
    ],
    collections: [makeCollection()],
    websites: [
      makeWebsite({
        latest_crawl: {
          ...(makeWebsite().latest_crawl as Record<string, unknown>),
          status: "failed"
        }
      })
    ],
    members: [makeMember()]
  });

describe("SpaceOverview", () => {
  it("shows the newest assistants and a compact knowledge list", async () => {
    const { container } = show(busySpace());

    const assistants = screen.getByRole("region", { name: "Assistenter" });
    expect(within(assistants).getByRole("link", { name: "Visa alla assistenter" })).toBeTruthy();
    // One row: two newest cards plus the create card for users who may create.
    const grid = within(assistants).getAllByRole("list")[0]!;
    const cards = Array.from(grid.children) as HTMLElement[];
    expect(cards).toHaveLength(3);
    expect(within(cards[0]!).getByRole("link", { name: "Avtalsgranskaren" })).toBeTruthy();
    expect(within(cards[0]!).getByText("Utkast")).toBeTruthy();
    expect(within(cards[0]!).getByText("claude-opus")).toBeTruthy();
    expect(within(cards[1]!).getByText("Publicerad")).toBeTruthy();
    expect(within(cards[1]!).getByText("Haiku 4.5")).toBeTruthy();
    expect(within(cards[2]!).getByText("Börja från en mall eller från noll")).toBeTruthy();
    expect(within(cards[2]!).getByRole("button", { name: "Skapa assistent" })).toBeTruthy();
    expect(within(assistants).queryByRole("link", { name: "Äldst" })).toBeNull();

    const knowledge = screen.getByRole("region", { name: "Kunskap" });
    // One column: knowledge follows the assistants.
    expect(knowledge.parentElement).toBe(assistants.parentElement);
    expect(within(knowledge).queryByRole("table")).toBeNull();
    expect(within(knowledge).getByText(/Samlingar, webbplatser och integrationer/)).toBeTruthy();
    const website = within(knowledge).getByRole("link", { name: "www.upphandlingsmyndigheten.se" });
    const websiteRow = website.closest("li")!;
    expect(within(websiteRow).getByText("Synkfel")).toBeTruthy();
    expect(within(websiteRow).getByText("318 sidor")).toBeTruthy();
    expect(
      within(websiteRow)
        .getByRole("link", { name: "Åtgärda www.upphandlingsmyndigheten.se" })
        .getAttribute("href")
    ).toBe("/spaces/space-1/knowledge/websites/website-1");
    const collectionRow = within(knowledge)
      .getByRole("link", { name: "Upphandlingspolicy" })
      .closest("li")!;
    expect(within(collectionRow).getByText("42 filer")).toBeTruthy();
    expect(within(collectionRow).getByText("Indexerad")).toBeTruthy();
    expect(
      within(collectionRow).getByRole("button", { name: "Fler åtgärder för Upphandlingspolicy" })
    ).toBeTruthy();
    expect(within(knowledge).getByRole("link", { name: "Visa alla kunskapskällor" })).toBeTruthy();

    await expectNoAxeViolations(container);
  });

  it("uploads to a chosen collection in the same dialog as the collection page", async () => {
    show(busySpace());

    const upload = screen.getByRole("button", { name: "Ladda upp" });
    fireEvent.click(upload);
    const item = await screen.findByRole("menuitem", { name: "Upphandlingspolicy" });
    await expectNoAxeViolations(document.body);
    fireEvent.click(item);

    // No detour to the collection page: the upload flow opens here, with the
    // accepted formats and limits.
    const dialog = await screen.findByRole("dialog", { name: "Ladda upp filer" });
    expect(within(dialog).getByText(/Upphandlingspolicy/)).toBeTruthy();
    expect(within(dialog).getByText(/pdf/i)).toBeTruthy();
    expect(router.push).not.toHaveBeenCalled();
  });

  it("shows empty states with the create actions in an empty space", async () => {
    const { container } = show(makeSpace());

    const assistants = screen.getByRole("region", { name: "Assistenter" });
    expect(within(assistants).getByRole("heading", { name: "Inga assistenter ännu" })).toBeTruthy();
    expect(within(assistants).getByRole("button", { name: "Skapa assistent" })).toBeTruthy();
    expect(within(assistants).queryByRole("link", { name: "Visa alla assistenter" })).toBeNull();

    const knowledge = screen.getByRole("region", { name: "Kunskap" });
    expect(within(knowledge).getByRole("heading", { name: "Inga källor ännu" })).toBeTruthy();
    expect(within(knowledge).getByRole("button", { name: "Skapa samling" })).toBeTruthy();
    expect(within(knowledge).queryByRole("button", { name: "Ladda upp" })).toBeNull();

    await expectNoAxeViolations(container);
  });

  it("leaves out what the user may not see or change", () => {
    show(
      makeSpace({
        resourcePermissions: ["read"],
        assistants: [makeAssistant()],
        collections: [makeCollection({ permissions: ["read"] })],
        overrides: { organization: false }
      })
    );

    const assistants = screen.getByRole("region", { name: "Assistenter" });
    // No create card without create permission: three cards fit instead.
    expect(within(assistants).queryByRole("button", { name: "Skapa assistent" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Ladda upp" })).toBeNull();
  });

  it("hides assistants in the organization space", () => {
    show(makeSpace({ overrides: { organization: true } }));
    expect(screen.queryByRole("region", { name: "Assistenter" })).toBeNull();
    expect(screen.getByRole("region", { name: "Kunskap" })).toBeTruthy();
  });
});
