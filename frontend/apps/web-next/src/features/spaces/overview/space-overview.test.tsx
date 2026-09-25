// @vitest-environment jsdom
import { cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { expectNoAxeViolations } from "@/test/axe";
import { renderInApp } from "@/test/render";
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

const state = vi.hoisted(() => ({
  space: null as unknown,
  push: (() => {}) as (href: string) => void
}));

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: (href: string) => state.push(href), prefetch: () => {} })
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
    user: { id: "user-1" },
    settings: { using_templates: true },
    limits: { attachments: { formats: [] }, info_blobs: { formats: [] } },
    can: () => true
  })
}));
vi.mock("@/features/jobs/use-jobs", () => ({
  useJobs: () => ({ trackJob: () => {}, queueUploads: () => {} })
}));

import { SpaceOverview } from "@/app/(app)/spaces/[spaceId]/overview/space-overview.client";

afterEach(cleanup);

function show(space: Space) {
  state.space = space;
  return renderInApp(<SpaceOverview />);
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
    members: [
      makeMember({ id: "u3", email: "sara@example.com", role: "viewer" }),
      makeMember(),
      makeMember({ id: "u2", email: "erik@example.com", role: "editor" }),
      makeMember({ id: "u4", email: "johan@example.com", role: "editor" }),
      makeMember({ id: "u5", email: "karin@example.com", role: "viewer" })
    ],
    overrides: {
      security_classification: { id: "sc", name: "Klass 2 · Intern", security_level: 2 }
    }
  });

describe("SpaceOverview", () => {
  it("shows the newest assistants, the knowledge table and the space facts", async () => {
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
    const table = within(knowledge).getByRole("table");
    expect(
      within(table)
        .getAllByRole("columnheader")
        .map((header) => header.textContent)
    ).toEqual(["Namn", "Typ", "Innehåll", "Status", "Uppdaterad", "Åtgärder"]);
    const website = within(table).getByRole("link", { name: "www.upphandlingsmyndigheten.se" });
    const websiteRow = website.closest("tr")!;
    expect(within(websiteRow).getByText("Synkfel")).toBeTruthy();
    expect(within(websiteRow).getByText("318 sidor")).toBeTruthy();
    expect(
      within(websiteRow)
        .getByRole("link", { name: "Åtgärda www.upphandlingsmyndigheten.se" })
        .getAttribute("href")
    ).toBe("/spaces/space-1/knowledge/websites/website-1");
    const collectionRow = within(table)
      .getByRole("link", { name: "Upphandlingspolicy" })
      .closest("tr")!;
    expect(within(collectionRow).getByText("42 filer")).toBeTruthy();
    expect(within(collectionRow).getByText("Indexerad")).toBeTruthy();
    expect(
      within(collectionRow).getByRole("button", { name: "Fler åtgärder för Upphandlingspolicy" })
    ).toBeTruthy();
    expect(within(knowledge).getByRole("link", { name: "Visa alla kunskapskällor" })).toBeTruthy();

    const about = screen.getByRole("region", { name: "Om ytan" });
    expect(within(about).getByText("Klass 2 · Intern")).toBeTruthy();
    expect(within(about).getByText("Haiku 4.5, claude-opus")).toBeTruthy();
    expect(within(about).getByText("multilingual-e5-large")).toBeTruthy();
    expect(within(about).getByText("12 mars 2026")).toBeTruthy();

    const members = screen.getByRole("region", { name: "Medlemmar" });
    const rows = within(members).getAllByRole("listitem");
    // Admins first, then editors and viewers; the avatar initial is decorative.
    expect(rows.map((row) => row.textContent)).toEqual([
      "Aanna.lind@example.comAdministratör",
      "Eerik@example.comRedigerare",
      "Jjohan@example.comRedigerare",
      "Kkarin@example.comVisare"
    ]);
    expect(rows[0]!.querySelector("[aria-hidden='true']")?.textContent).toBe("A");
    expect(
      within(members).getByRole("link", { name: "Hantera medlemmar" }).getAttribute("href")
    ).toBe("/spaces/space-1/members");

    await expectNoAxeViolations(container);
  });

  it("offers the space's collections as upload targets", async () => {
    const pushed: string[] = [];
    state.push = (href) => pushed.push(href);
    show(busySpace());

    const upload = screen.getByRole("button", { name: "Ladda upp" });
    fireEvent.click(upload);
    const item = await screen.findByRole("menuitem", { name: "Upphandlingspolicy" });
    await expectNoAxeViolations(document.body);
    fireEvent.click(item);
    await waitFor(() =>
      expect(pushed).toEqual(["/spaces/space-1/knowledge/collections/collection-1"])
    );
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
    expect(screen.getByRole("region", { name: "Medlemmar" })).toBeTruthy();
  });

  it("hides assistants and members in the organization space", () => {
    show(makeSpace({ overrides: { organization: true } }));
    expect(screen.queryByRole("region", { name: "Assistenter" })).toBeNull();
    expect(screen.queryByRole("region", { name: "Medlemmar" })).toBeNull();
    expect(screen.getByRole("region", { name: "Kunskap" })).toBeTruthy();
  });
});
