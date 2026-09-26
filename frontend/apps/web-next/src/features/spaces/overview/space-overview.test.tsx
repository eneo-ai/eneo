// @vitest-environment jsdom
import { cleanup, fireEvent, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { expectNoAxeViolations } from "@/test/axe";
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

const itemTexts = (list: HTMLElement) =>
  within(list)
    .getAllByRole("listitem")
    .map((item) => item.textContent);

/**
 * Presses Enter or Space on a native button as a browser does: Enter clicks on
 * keydown, Space on keyup. jsdom fires the key events but not the click.
 */
function press(button: HTMLElement, key: "Enter" | " ") {
  expect(button.tagName).toBe("BUTTON");
  fireEvent.keyDown(button, { key });
  if (key === "Enter") fireEvent.click(button);
  fireEvent.keyUp(button, { key });
  if (key === " ") fireEvent.click(button);
}

/** Models as the space API returns them, in its order. */
const models = (names: string[], defaultName?: string) =>
  names.map((name, index) => ({
    id: `${name}-${index}`,
    name,
    nickname: null,
    is_org_default: name === defaultName
  }));

// A real space's chat models: 15 ids, the organization's default fifth.
const CHAT_MODELS = [
  "claude-3-7-sonnet-20250219",
  "claude-haiku-4-5",
  "gpt-4o",
  "gpt-4o-mini",
  "gpt-5.4-2026-03-05",
  "gpt-5-mini",
  "mistral-large-2411",
  "mistral-small-2503",
  "llama-3.3-70b-instruct",
  "gemma-3-27b-it",
  "qwen3-235b-a22b",
  "claude-opus-4-1-20250805",
  "o3-mini",
  "o4-mini",
  "gemini-2.5-pro"
];
const EMBEDDING_MODELS = [
  "multilingual-e5-large",
  "text-embedding-3-large",
  "text-embedding-3-small",
  "bge-m3",
  "nomic-embed-text-v1.5"
];

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
    // Named by the section heading, like the tables on the knowledge page.
    const table = within(knowledge).getByRole("table", { name: "Kunskap" });
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
    // A few models: every name on its own line, no button.
    expect(within(about).getAllByRole("list").map(itemTexts)).toEqual([
      ["Haiku 4.5", "claude-opus"],
      ["multilingual-e5-large"]
    ]);
    expect(within(about).queryByRole("button")).toBeNull();
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

  it("uploads to a chosen collection in the same dialog as the collection page", async () => {
    const pushed: string[] = [];
    state.push = (href) => pushed.push(href);
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
    expect(pushed).toEqual([]);
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

describe("SpaceOverview: models in Om ytan", () => {
  it("shows the default and two more of many models, and the rest from the keyboard", async () => {
    const { container } = show(
      makeSpace({
        overrides: {
          completion_models: models(CHAT_MODELS, "gpt-5.4-2026-03-05"),
          embedding_models: models(EMBEDDING_MODELS)
        }
      })
    );
    const about = screen.getByRole("region", { name: "Om ytan" });

    // The count is on the button; its name says which models it shows.
    const toggle = within(about).getByRole("button", { name: "Visa alla 15 chattmodeller" });
    expect(toggle.textContent).toBe("Visa alla 15");
    expect(toggle.getAttribute("aria-expanded")).toBe("false");
    const list = document.getElementById(toggle.getAttribute("aria-controls")!)!;
    expect(itemTexts(list)).toEqual([
      "gpt-5.4-2026-03-05Standard",
      "claude-3-7-sonnet-20250219",
      "claude-haiku-4-5"
    ]);
    await expectNoAxeViolations(container);

    toggle.focus();
    press(toggle, "Enter");
    expect(document.activeElement).toBe(toggle);
    expect(toggle.getAttribute("aria-expanded")).toBe("true");
    expect(within(about).getByRole("button", { name: "Visa färre chattmodeller" })).toBe(toggle);
    expect(toggle.textContent).toBe("Visa färre");
    const all = itemTexts(list).map((text) => text!.replace(/Standard$/, ""));
    expect(all).toHaveLength(15);
    expect([...all].sort()).toEqual([...CHAT_MODELS].sort());
    await expectNoAxeViolations(container);

    press(toggle, " ");
    expect(document.activeElement).toBe(toggle);
    expect(toggle.getAttribute("aria-expanded")).toBe("false");
    expect(itemTexts(list)).toHaveLength(3);

    // Embedding models get the same treatment, with a button of their own.
    const embedding = within(about).getByRole("button", {
      name: "Visa alla 5 inbäddningsmodeller"
    });
    const embeddingList = document.getElementById(embedding.getAttribute("aria-controls")!)!;
    expect(itemTexts(embeddingList)).toEqual(EMBEDDING_MODELS.slice(0, 3));
    fireEvent.click(embedding);
    expect(itemTexts(embeddingList)).toEqual(EMBEDDING_MODELS);
    // Each list opens on its own.
    expect(itemTexts(list)).toHaveLength(3);
  });

  it("shows up to four models without a button", () => {
    show(makeSpace({ overrides: { completion_models: models(CHAT_MODELS.slice(0, 4)) } }));
    const about = screen.getByRole("region", { name: "Om ytan" });
    expect(itemTexts(within(about).getAllByRole("list")[0]!)).toEqual(CHAT_MODELS.slice(0, 4));
    expect(within(about).queryByRole("button")).toBeNull();
  });
});
