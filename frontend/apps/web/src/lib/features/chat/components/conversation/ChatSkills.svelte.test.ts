import "../../../../../app.css";
import {
  EneoError,
  type AssistantSkillBindingSummary,
  type AssistantSkillConfiguration,
  type SkillSparse
} from "@eneo/eneo-js";
import { page, userEvent } from "vitest/browser";
import { render } from "vitest-browser-svelte";
import { beforeEach, describe, expect, it, vi } from "vitest";
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

function ownSkillRow(name: string) {
  return page.getByRole("listitem").filter({ hasText: name });
}

async function openControl(count: number) {
  await page.getByRole("button", { name: m.personal_chat_skills_button_label({ count }) }).click();
}

describe("ChatSkills", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.permissions = new Set(["personal_chat", "personal_skills"]);
    mocks.getAssistantConfiguration.mockResolvedValue(configuration());
    mocks.list.mockResolvedValue(libraryPage(LIBRARY));
    mocks.updateDefaultAssistantSkills.mockResolvedValue(undefined);
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
      .element(
        modeGroup("Engelsk översättning").getByRole("radio", {
          name: m.personal_chat_skills_mode_off()
        })
      )
      .toBeChecked();
    await expect
      .element(page.getByRole("link", { name: m.personal_chat_skills_manage() }))
      .toHaveAttribute("href", "/spaces/personal/skills");
    await expectNoAxeViolations(document.body);
  });

  it("shows a choice at once and saves the full ordered list of the person's own Skills", async () => {
    let finishSave!: () => void;
    mocks.updateDefaultAssistantSkills.mockReturnValue(
      new Promise<void>((resolve) => (finishSave = resolve))
    );
    renderControl();
    await openControl(3);

    const always = modeGroup("Engelsk översättning").getByRole("radio", {
      name: m.skills_activation_mode_always()
    });
    await always.click();

    await expect.element(always).toBeChecked();
    expect(mocks.updateDefaultAssistantSkills).toHaveBeenCalledWith({ id: "default-assistant" }, [
      { skill_id: "answers", skill_revision_id: "answers-r1", activation_mode: "always" },
      { skill_id: "minutes", skill_revision_id: "minutes-r1", activation_mode: "on_demand" },
      { skill_id: "translate", skill_revision_id: "translate-r1", activation_mode: "always" }
    ]);
    mocks.getAssistantConfiguration.mockResolvedValue(
      configuration({
        bindings: [ANSWERS, MINUTES, binding("translate", "Engelsk översättning", { position: 2 })]
      })
    );
    finishSave();
    await expect
      .element(page.getByText(m.personal_chat_skills_counts({ always: 3, on_demand: 1 })))
      .toBeVisible();
    await expect.element(always).toBeChecked();
  });

  it("moves the choice with the arrow keys, one tab stop per Skill", async () => {
    renderControl();
    await openControl(3);

    const onDemand = modeGroup("Mötesanteckningar").getByRole("radio", {
      name: m.skills_activation_mode_on_demand()
    });
    await onDemand.click();
    expect(mocks.updateDefaultAssistantSkills).not.toHaveBeenCalled();
    await userEvent.keyboard("{ArrowRight}");

    await expect
      .element(
        modeGroup("Mötesanteckningar").getByRole("radio", {
          name: m.skills_activation_mode_always()
        })
      )
      .toHaveFocus();
    expect(mocks.updateDefaultAssistantSkills).toHaveBeenCalledWith({ id: "default-assistant" }, [
      { skill_id: "answers", skill_revision_id: "answers-r1", activation_mode: "always" },
      { skill_id: "minutes", skill_revision_id: "minutes-r1", activation_mode: "always" }
    ]);
  });

  it("rolls a refused change back and says why next to the Skill", async () => {
    mocks.updateDefaultAssistantSkills.mockRejectedValue(
      new EneoError("Refused", "RESPONSE", 400, 9080, {
        eneo_error_code: 9080,
        details: { reason: "on_demand_unavailable", detail: "selective_activation_disabled" }
      })
    );
    renderControl();
    await openControl(3);

    await modeGroup("Engelsk översättning")
      .getByRole("radio", { name: m.skills_activation_mode_on_demand() })
      .click();

    await expect
      .element(
        page.getByRole("alert").getByText(m.personal_chat_skills_reason_on_demand_disabled())
      )
      .toBeVisible();
    await expect
      .element(
        modeGroup("Engelsk översättning").getByRole("radio", {
          name: m.personal_chat_skills_mode_off()
        })
      )
      .toBeChecked();
  });

  it("explains paused own Skills and counts only the organisation's", async () => {
    mocks.getAssistantConfiguration.mockResolvedValue(
      configuration({
        personal_layer: { status: "suspended", reason: "model_context_exceeded", detail: null }
      })
    );
    renderControl();
    await openControl(1);

    await expect.element(page.getByText(m.personal_chat_skills_paused_title())).toBeVisible();
    await expect
      .element(page.getByText(m.personal_chat_skills_reason_model_context_exceeded()))
      .toBeVisible();
    // Switching off stays possible while paused: it is the way out.
    await modeGroup("Mötesanteckningar")
      .getByRole("radio", { name: m.personal_chat_skills_mode_off() })
      .click();
    expect(mocks.updateDefaultAssistantSkills).toHaveBeenCalledWith({ id: "default-assistant" }, [
      { skill_id: "answers", skill_revision_id: "answers-r1", activation_mode: "always" }
    ]);
  });

  it("offers to create a first Skill when the person has none", async () => {
    mocks.getAssistantConfiguration.mockResolvedValue(
      configuration({
        bindings: [],
        personal_layer: { status: "empty", reason: null, detail: null }
      })
    );
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
    mocks.getAssistantConfiguration.mockResolvedValue(
      configuration({
        bindings: [ANSWERS],
        personal_layer: { status: "suspended", reason: "permission_missing", detail: null }
      })
    );
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
    mocks.getAssistantConfiguration.mockResolvedValue(
      configuration({ bindings: [], organisation_bindings: [], personal_layer: null })
    );
    renderControl();

    await vi.waitFor(() => expect(mocks.getAssistantConfiguration).toHaveBeenCalled());
    await expect
      .element(page.getByRole("button", { name: /personliga chatt|personal chat/ }))
      .not.toBeInTheDocument();
  });

  it("moves a Skill to its latest version when the person chooses it", async () => {
    mocks.getAssistantConfiguration.mockResolvedValue(
      configuration({
        bindings: [
          { ...ANSWERS, attachable_revision_id: "answers-r2", attachable_revision_number: 2 },
          MINUTES
        ]
      })
    );
    renderControl();
    await openControl(3);

    await expect.element(page.getByText(m.personal_chat_skills_update_available())).toBeVisible();
    await page.getByRole("button", { name: m.personal_chat_skills_use_latest() }).click();

    expect(mocks.updateDefaultAssistantSkills).toHaveBeenCalledWith({ id: "default-assistant" }, [
      { skill_id: "answers", skill_revision_id: "answers-r2", activation_mode: "always" },
      { skill_id: "minutes", skill_revision_id: "minutes-r1", activation_mode: "on_demand" }
    ]);
  });

  it("keeps a Skill blocked by an administrator out of reach", async () => {
    mocks.getAssistantConfiguration.mockResolvedValue(
      configuration({ bindings: [ANSWERS, { ...MINUTES, execution_blocked: true }] })
    );
    renderControl();
    await openControl(2);

    await expect
      .element(ownSkillRow("Mötesanteckningar").getByText(m.personal_chat_skills_blocked()))
      .toBeVisible();
    expect(modeGroup("Mötesanteckningar").elements()).toHaveLength(0);
    await expect.element(modeGroup("Mina svarspreferenser")).toBeVisible();
  });

  it("searches the person's own Skills once there are more than seven", async () => {
    mocks.list.mockResolvedValue(
      libraryPage(
        Array.from({ length: 8 }, (_, index) => librarySkill(`skill-${index}`, `Skill ${index}`))
      )
    );
    mocks.getAssistantConfiguration.mockResolvedValue(configuration({ bindings: [] }));
    renderControl();
    await openControl(1);

    const search = page.getByRole("searchbox", { name: m.personal_chat_skills_search() });
    await search.fill("Skill 7");
    await expect.element(modeGroup("Skill 7")).toBeVisible();
    expect(modeGroup("Skill 6").elements()).toHaveLength(0);

    await search.fill("nothing like it");
    await expect.element(page.getByText(m.personal_chat_skills_search_empty())).toBeVisible();
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
