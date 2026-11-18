import "../../../../../app.css";
import {
  EneoError,
  type AssistantSkillBindingInput,
  type AssistantSkillBindingSummary,
  type AssistantSkillConfiguration,
  type SkillSparse
} from "@eneo/eneo-js";
import { page, userEvent } from "vitest/browser";
import { render } from "vitest-browser-svelte";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { SKILL_CATALOG_PAGE_SIZE } from "$lib/features/skills/skillCatalog";
import { m } from "$lib/paraglide/messages";
import { expectNoAxeViolations } from "$lib/test/axe";

const mocks = vi.hoisted(() => ({
  permissions: new Set<string>(),
  getAssistantConfiguration: vi.fn(),
  list: vi.fn(),
  updateDefaultAssistantSkills: vi.fn()
}));

vi.mock("$app/paths", () => ({ resolve: (path: string) => path }));
vi.mock("$lib/core/AppContext", async () => {
  const { hasPermission } = await import("$lib/core/hasPermission");
  return {
    getAppContext: () => ({
      user: {
        hasPermission: (required: Parameters<ReturnType<typeof hasPermission>>[0]) =>
          hasPermission({ roles: [{ permissions: [...mocks.permissions] } as never] })(required)
      }
    })
  };
});
vi.mock("$lib/core/Eneo", () => ({
  getEneo: () => ({
    skills: { getAssistantConfiguration: mocks.getAssistantConfiguration, list: mocks.list }
  })
}));
vi.mock("$lib/features/spaces/SpacesManager", async () => {
  const { writable } = await import("svelte/store");
  return {
    getSpacesManager: () => ({
      state: {
        currentSpace: writable({
          id: "personal-space",
          personal: true,
          skill_permissions: ["read", "create"],
          default_assistant: { id: "default-assistant", completion_model: { id: "model" } }
        })
      },
      updateDefaultAssistantSkills: mocks.updateDefaultAssistantSkills,
      awaitDefaultAssistantUpdates: async () => {}
    })
  };
});

import ChatSkills from "./ChatSkills.svelte";

function binding(
  id: string,
  name: string,
  overrides: Partial<AssistantSkillBindingSummary> = {}
): AssistantSkillBindingSummary {
  return {
    skill_id: id,
    skill_revision_id: `${id}-r1`,
    attachable_revision_id: `${id}-r1`,
    slug: id,
    revision_number: 1,
    attachable_revision_number: 1,
    display_name: name,
    description: `About ${name}`,
    content_digest: "digest",
    position: 0,
    is_active: true,
    source: "space",
    execution_blocked: false,
    activation_mode: "always",
    ...overrides
  };
}

function librarySkill(id: string, name: string): SkillSparse {
  return {
    id,
    space_id: "personal-space",
    slug: id,
    is_active: true,
    current_revision_id: `${id}-r1`,
    current_revision_number: 1,
    display_name: name,
    description: `About ${name}`,
    content_digest: "digest",
    created_by_user_id: "user-1",
    created_at: "2026-10-21T08:00:00Z",
    updated_at: "2026-10-21T08:00:00Z"
  };
}

const ORGANISATION = binding("plain", "Klarspråk", { source: "organization" });
const ANSWERS = binding("answers", "Mina svarspreferenser");
const MINUTES = binding("minutes", "Mötesanteckningar", {
  position: 1,
  activation_mode: "on_demand"
});
const TRANSLATE = binding("translate", "Engelsk översättning");
const LIBRARY = [
  librarySkill("answers", "Mina svarspreferenser"),
  librarySkill("minutes", "Mötesanteckningar"),
  librarySkill("translate", "Engelsk översättning")
];

function configuration(
  overrides: Partial<AssistantSkillConfiguration> = {}
): AssistantSkillConfiguration {
  return {
    bindings: [ANSWERS, MINUTES],
    organisation_bindings: [ORGANISATION],
    runtime: null,
    personal_layer: { status: "applied", reason: null, detail: null },
    ...overrides
  };
}

/**
 * The personal chat as the backend holds it, behind the default-assistant
 * queue: each save builds its list when its turn comes and replaces the saved
 * Skills unless `refuse` turns it down. `hold` keeps the save in flight.
 */
function personalChatServer(overrides: Partial<AssistantSkillConfiguration> = {}) {
  let saved = configuration(overrides).bindings;
  let queue = Promise.resolve();
  const server = {
    sent: [] as AssistantSkillBindingInput[][],
    hold: null as Promise<void> | null,
    refuse: (_bindings: AssistantSkillBindingInput[]): unknown => null
  };
  mocks.getAssistantConfiguration.mockImplementation(async () =>
    configuration({ ...overrides, bindings: saved })
  );
  mocks.updateDefaultAssistantSkills.mockImplementation(
    (_assistant: unknown, build: () => Promise<AssistantSkillBindingInput[]>) => {
      const run = async () => {
        const bindings = await build();
        server.sent.push(bindings);
        if (server.hold) await server.hold;
        const refused = server.refuse(bindings);
        if (refused) throw refused;
        saved = bindings.map((input, position) => ({
          ...(saved.find((b) => b.skill_id === input.skill_id) ??
            [ANSWERS, MINUTES, TRANSLATE].find((b) => b.skill_id === input.skill_id)!),
          skill_revision_id: input.skill_revision_id,
          activation_mode: input.activation_mode ?? "always",
          position
        }));
      };
      const result = queue.then(run, run);
      queue = result.catch(() => {});
      return result;
    }
  );
  return server;
}

function refusal(reason: string, detail: string | null = null) {
  return new EneoError("Refused", "RESPONSE", 400, 9080, {
    eneo_error_code: 9080,
    details: { reason, detail }
  });
}

function libraryPage(items: SkillSparse[]) {
  return { items, next_cursor: null };
}

function renderControl(width = "48rem") {
  // The control sits in the composer's query container, as in ChatComposer.
  const composer = document.createElement("div");
  composer.className = "@container/composer";
  composer.style.width = width;
  document.body.append(composer);
  render(ChatSkills, { target: composer });
}

function modeGroup(name: string) {
  return page.getByRole("radiogroup", { name: m.personal_chat_skills_mode_group_label({ name }) });
}

function mode(name: string, label: string) {
  return modeGroup(name).getByRole("radio", { name: label });
}

function ownSkillRow(name: string) {
  return page.getByRole("listitem").filter({ hasText: name });
}

async function openControl(count: number) {
  await page.getByRole("button", { name: m.personal_chat_skills_button_label({ count }) }).click();
}

describe("ChatSkills", () => {
  let server: ReturnType<typeof personalChatServer>;

  beforeEach(() => {
    vi.clearAllMocks();
    mocks.permissions = new Set(["personal_chat", "personal_skills"]);
    mocks.list.mockResolvedValue(libraryPage(LIBRARY));
    server = personalChatServer();
  });

  it("is named Skills until it knows how many run", async () => {
    mocks.getAssistantConfiguration.mockReturnValue(new Promise(() => {}));
    renderControl();

    await expect
      .element(page.getByRole("button", { name: m.personal_chat_skills_button(), exact: true }))
      .toBeVisible();
  });

  it("names the Skills that run and lists the organisation's apart from the person's own", async () => {
    renderControl();
    await openControl(3);

    await expect.element(page.getByText(m.personal_chat_skills_scope())).toBeVisible();
    await expect
      .element(page.getByText(m.personal_chat_skills_counts({ always: 2, on_demand: 1 })))
      .toBeVisible();
    await expect.element(page.getByText("Klarspråk", { exact: true })).toBeVisible();
    await expect
      .element(page.getByText(m.personal_chat_skills_organisation_locked()))
      .toBeVisible();
    // The organisation's Skills are not a choice.
    expect(modeGroup("Klarspråk").elements()).toHaveLength(0);
    await expect
      .element(mode("Engelsk översättning", m.personal_chat_skills_mode_off()))
      .toBeChecked();
    await expect
      .element(page.getByRole("link", { name: m.personal_chat_skills_manage() }))
      .toHaveAttribute("href", "/spaces/personal/skills");
    // One bounded page of the library, not all of it.
    expect(mocks.list).toHaveBeenCalledOnce();
    expect(mocks.list).toHaveBeenCalledWith({
      spaceId: "personal-space",
      limit: SKILL_CATALOG_PAGE_SIZE,
      cursor: null,
      query: null
    });
    await expectNoAxeViolations(document.body);
  });

  it("shows a choice at once and saves the full ordered list of the person's own Skills", async () => {
    let release!: () => void;
    server.hold = new Promise((resolve) => (release = resolve));
    renderControl();
    await openControl(3);

    const always = mode("Engelsk översättning", m.skills_activation_mode_always());
    await always.click();

    await expect.element(always).toBeChecked();
    await vi.waitFor(() =>
      expect(server.sent).toEqual([
        [
          { skill_id: "answers", skill_revision_id: "answers-r1", activation_mode: "always" },
          { skill_id: "minutes", skill_revision_id: "minutes-r1", activation_mode: "on_demand" },
          { skill_id: "translate", skill_revision_id: "translate-r1", activation_mode: "always" }
        ]
      ])
    );
    expect(mocks.updateDefaultAssistantSkills).toHaveBeenCalledWith(
      { id: "default-assistant" },
      expect.any(Function)
    );
    release();
    await expect
      .element(page.getByText(m.personal_chat_skills_counts({ always: 3, on_demand: 1 })))
      .toBeVisible();
    await expect.element(always).toBeChecked();
  });

  it("moves the choice with the arrow keys, one tab stop per Skill", async () => {
    renderControl();
    await openControl(3);

    await mode("Mötesanteckningar", m.skills_activation_mode_on_demand()).click();
    expect(mocks.updateDefaultAssistantSkills).not.toHaveBeenCalled();
    await userEvent.keyboard("{ArrowRight}");

    await expect
      .element(mode("Mötesanteckningar", m.skills_activation_mode_always()))
      .toHaveFocus();
    await vi.waitFor(() =>
      expect(server.sent).toEqual([
        [
          { skill_id: "answers", skill_revision_id: "answers-r1", activation_mode: "always" },
          { skill_id: "minutes", skill_revision_id: "minutes-r1", activation_mode: "always" }
        ]
      ])
    );
  });

  it("rolls a refused change back, says why next to the Skill, and forgets it on close", async () => {
    server.refuse = (bindings) =>
      bindings.some((b) => b.skill_id === "translate") &&
      refusal("on_demand_unavailable", "selective_activation_disabled");
    renderControl();
    await openControl(3);

    await mode("Engelsk översättning", m.skills_activation_mode_on_demand()).click();

    await expect
      .element(ownSkillRow("Engelsk översättning").getByRole("alert"))
      .toHaveTextContent(m.personal_chat_skills_reason_on_demand_disabled());
    await expect
      .element(mode("Engelsk översättning", m.personal_chat_skills_mode_off()))
      .toBeChecked();

    await userEvent.keyboard("{Escape}");
    await openControl(3);
    await expect.element(modeGroup("Engelsk översättning")).toBeVisible();
    expect(page.getByRole("alert").elements()).toHaveLength(0);
  });

  it("saves each change on its own, so a refused one neither travels with a later one nor blames it", async () => {
    let release!: () => void;
    server.hold = new Promise((resolve) => (release = resolve));
    server.refuse = (bindings) =>
      bindings.some((b) => b.skill_id === "translate") && refusal("attachment_limit_exceeded");
    renderControl();
    await openControl(3);

    // A: one Skill too many; B: switch another off while A is still saving.
    await mode("Engelsk översättning", m.skills_activation_mode_always()).click();
    await mode("Mötesanteckningar", m.personal_chat_skills_mode_off()).click();
    await expect
      .element(mode("Engelsk översättning", m.skills_activation_mode_always()))
      .toBeChecked();
    await expect
      .element(mode("Mötesanteckningar", m.personal_chat_skills_mode_off()))
      .toBeChecked();
    server.hold = null;
    release();

    await expect
      .element(ownSkillRow("Engelsk översättning").getByRole("alert"))
      .toHaveTextContent(m.personal_chat_skills_reason_attachment_limit_exceeded());
    await expect
      .element(mode("Engelsk översättning", m.personal_chat_skills_mode_off()))
      .toBeChecked();
    await expect
      .element(mode("Mötesanteckningar", m.personal_chat_skills_mode_off()))
      .toBeChecked();
    expect(ownSkillRow("Mötesanteckningar").getByRole("alert").elements()).toHaveLength(0);
    expect(server.sent).toEqual([
      [
        { skill_id: "answers", skill_revision_id: "answers-r1", activation_mode: "always" },
        { skill_id: "minutes", skill_revision_id: "minutes-r1", activation_mode: "on_demand" },
        { skill_id: "translate", skill_revision_id: "translate-r1", activation_mode: "always" }
      ],
      [{ skill_id: "answers", skill_revision_id: "answers-r1", activation_mode: "always" }]
    ]);
  });

  it("explains paused own Skills and counts only the organisation's", async () => {
    server = personalChatServer({
      personal_layer: { status: "suspended", reason: "model_context_exceeded", detail: null }
    });
    renderControl();
    await openControl(1);

    await expect.element(page.getByText(m.personal_chat_skills_paused_title())).toBeVisible();
    await expect
      .element(page.getByText(m.personal_chat_skills_reason_model_context_exceeded()))
      .toBeVisible();
    // Switching off stays possible while paused: it is the way out.
    await mode("Mötesanteckningar", m.personal_chat_skills_mode_off()).click();
    await vi.waitFor(() =>
      expect(server.sent).toEqual([
        [{ skill_id: "answers", skill_revision_id: "answers-r1", activation_mode: "always" }]
      ])
    );
  });

  it("offers to create a first Skill when the person has none", async () => {
    server = personalChatServer({
      bindings: [],
      personal_layer: { status: "empty", reason: null, detail: null }
    });
    mocks.list.mockResolvedValue(libraryPage([]));
    renderControl();
    await openControl(1);

    await expect.element(page.getByText(m.personal_chat_skills_empty())).toBeVisible();
    await expect
      .element(page.getByRole("link", { name: m.skills_library_create() }))
      .toHaveAttribute("href", "/spaces/personal/skills/new");
  });

  it("shows retained own Skills read-only, with no library, when the role no longer allows them", async () => {
    mocks.permissions = new Set(["personal_chat"]);
    server = personalChatServer({
      bindings: [ANSWERS],
      personal_layer: { status: "suspended", reason: "permission_missing", detail: null }
    });
    renderControl();
    await openControl(1);

    await expect
      .element(page.getByText(m.personal_chat_skills_reason_permission_missing()))
      .toBeVisible();
    // The saved mode is told, not offered.
    expect(modeGroup("Mina svarspreferenser").elements()).toHaveLength(0);
    await expect
      .element(
        ownSkillRow("Mina svarspreferenser").getByText(m.skills_activation_mode_always(), {
          exact: true
        })
      )
      .toBeVisible();
    expect(mocks.list).not.toHaveBeenCalled();
    expect(
      page.getByRole("link", { name: m.personal_chat_skills_manage() }).elements()
    ).toHaveLength(0);
  });

  it("stays out of the toolbar when there is nothing to show or choose", async () => {
    mocks.permissions = new Set();
    server = personalChatServer({ bindings: [], organisation_bindings: [], personal_layer: null });
    renderControl();

    await vi.waitFor(() => expect(mocks.getAssistantConfiguration).toHaveBeenCalled());
    await expect
      .element(page.getByRole("button", { name: /personliga chatt|personal chat/ }))
      .not.toBeInTheDocument();
  });

  it("moves a Skill to its latest version when the person chooses it", async () => {
    server = personalChatServer({
      bindings: [
        { ...ANSWERS, attachable_revision_id: "answers-r2", attachable_revision_number: 2 },
        MINUTES
      ]
    });
    renderControl();
    await openControl(3);

    await expect.element(page.getByText(m.personal_chat_skills_update_available())).toBeVisible();
    await page.getByRole("button", { name: m.personal_chat_skills_use_latest() }).click();

    await vi.waitFor(() =>
      expect(server.sent).toEqual([
        [
          { skill_id: "answers", skill_revision_id: "answers-r2", activation_mode: "always" },
          { skill_id: "minutes", skill_revision_id: "minutes-r1", activation_mode: "on_demand" }
        ]
      ])
    );
    await expect
      .element(page.getByText(m.personal_chat_skills_update_available()))
      .not.toBeInTheDocument();
  });

  it("keeps a Skill blocked by an administrator out of reach", async () => {
    server = personalChatServer({ bindings: [ANSWERS, { ...MINUTES, execution_blocked: true }] });
    renderControl();
    await openControl(2);

    await expect
      .element(ownSkillRow("Mötesanteckningar").getByText(m.personal_chat_skills_blocked()))
      .toBeVisible();
    expect(modeGroup("Mötesanteckningar").elements()).toHaveLength(0);
    await expect.element(modeGroup("Mina svarspreferenser")).toBeVisible();
  });

  it("searches the person's own Skills on the server once there are more than seven", async () => {
    const skills = Array.from({ length: 8 }, (_, index) =>
      librarySkill(`skill-${index}`, `Skill ${index}`)
    );
    mocks.list.mockImplementation(async ({ query }: { query: string | null }) =>
      libraryPage(query ? skills.filter((skill) => skill.display_name.includes(query)) : skills)
    );
    server = personalChatServer({ bindings: [] });
    renderControl();
    await openControl(1);

    const search = page.getByRole("searchbox", { name: m.personal_chat_skills_search() });
    await search.fill("Skill 7");
    await vi.waitFor(() => expect(modeGroup("Skill 6").elements()).toHaveLength(0));
    await expect.element(modeGroup("Skill 7")).toBeVisible();
    expect(mocks.list).toHaveBeenLastCalledWith(expect.objectContaining({ query: "Skill 7" }));

    await search.fill("nothing like it");
    await expect.element(page.getByText(m.personal_chat_skills_search_empty())).toBeVisible();
  });

  it("pages the library in and keeps the Skills in the chat usable when a later page fails", async () => {
    mocks.list.mockImplementation(async ({ cursor }: { cursor: string | null }) => {
      if (cursor) throw new Error("offline");
      return { items: [librarySkill("translate", "Engelsk översättning")], next_cursor: "page-2" };
    });
    renderControl();
    await openControl(3);

    // In the chat, though no loaded page lists them.
    await expect.element(modeGroup("Mötesanteckningar")).toBeVisible();
    await expect.element(modeGroup("Mina svarspreferenser")).toBeVisible();
    // More to come, so it can be searched.
    await expect
      .element(page.getByRole("searchbox", { name: m.personal_chat_skills_search() }))
      .toBeVisible();
    await page.getByRole("button", { name: m.load_more() }).click();
    await expect.element(page.getByRole("alert").getByText(m.request_failed())).toBeVisible();

    await mode("Mötesanteckningar", m.personal_chat_skills_mode_off()).click();
    await vi.waitFor(() =>
      expect(server.sent).toEqual([
        [{ skill_id: "answers", skill_revision_id: "answers-r1", activation_mode: "always" }]
      ])
    );
    expect(mocks.list).toHaveBeenCalledTimes(2);
  });

  it("offers no version move for a deactivated Skill in the chat", async () => {
    server = personalChatServer({
      bindings: [{ ...ANSWERS, is_active: false, attachable_revision_id: "answers-r2" }, MINUTES]
    });
    renderControl();
    await openControl(3);

    await expect.element(modeGroup("Mina svarspreferenser")).toBeVisible();
    await expect
      .element(page.getByRole("button", { name: m.personal_chat_skills_use_latest() }))
      .not.toBeInTheDocument();
    expect(server.sent).toEqual([]);
  });

  it("offers the next page when a page holds no Skill that can join the chat", async () => {
    server = personalChatServer({ bindings: [] });
    mocks.list.mockImplementation(async ({ cursor }: { cursor: string | null }) =>
      cursor
        ? libraryPage([librarySkill("translate", "Engelsk översättning")])
        : {
            items: [{ ...librarySkill("old", "Gammal skill"), is_active: false }],
            next_cursor: "page-2"
          }
    );
    renderControl();
    await openControl(1);

    const loadMore = page.getByRole("button", { name: m.load_more() });
    await expect.element(loadMore).toBeVisible();
    await expect.element(page.getByText(m.personal_chat_skills_empty())).not.toBeInTheDocument();
    await loadMore.click();
    await expect.element(modeGroup("Engelsk översättning")).toBeVisible();
  });

  it("lets a later choice for the same Skill replace an earlier refusal", async () => {
    let release!: () => void;
    server.hold = new Promise((resolve) => (release = resolve));
    server.refuse = (bindings) =>
      bindings.some((b) => b.skill_id === "translate" && b.activation_mode === "on_demand") &&
      refusal("on_demand_unavailable", "model_lacks_tool_calling");
    renderControl();
    await openControl(3);

    await mode("Engelsk översättning", m.skills_activation_mode_on_demand()).click();
    await mode("Engelsk översättning", m.skills_activation_mode_always()).click();
    server.hold = null;
    release();

    await expect
      .element(page.getByText(m.personal_chat_skills_counts({ always: 3, on_demand: 1 })))
      .toBeVisible();
    await expect
      .element(mode("Engelsk översättning", m.skills_activation_mode_always()))
      .toBeChecked();
    expect(server.sent).toHaveLength(2);
    expect(ownSkillRow("Engelsk översättning").getByRole("alert").elements()).toHaveLength(0);
  });

  it("opens the same choices in a bottom sheet in a narrow composer", async () => {
    renderControl("20rem");
    await openControl(3);

    const sheet = page.getByRole("dialog", { name: m.personal_chat_skills_button() });
    await expect.element(sheet).toHaveAttribute("data-slot", "sheet-content");
    await expect.element(sheet.getByRole("radiogroup").first()).toBeVisible();
    await expectNoAxeViolations(document.body);

    const close = sheet.getByRole("button", { name: m.close(), exact: true });
    await expect.element(close).toHaveTextContent(m.close());
    await close.click();
    await expect.element(sheet).not.toBeInTheDocument();
  });
});
