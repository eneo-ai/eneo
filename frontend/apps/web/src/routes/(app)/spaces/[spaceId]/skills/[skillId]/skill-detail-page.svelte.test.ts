import {
  EneoError,
  type AssistantSkillConfiguration,
  type SkillPublic,
  type SkillRevisionPublic,
  type SkillRevisionSummaryPage
} from "@eneo/eneo-js";
import { page } from "@vitest/browser/context";
import { render } from "vitest-browser-svelte";
import { beforeEach, describe, expect, test, vi } from "vitest";
import { m } from "$lib/paraglide/messages";

const invalidate = vi.hoisted(() => vi.fn(async () => {}));
const updateDefaultAssistantSkills = vi.hoisted(() =>
  vi.fn(async (_assistant: { id: string }, _bindings: () => Promise<unknown>) => {})
);

vi.mock("$lib/features/spaces/SpacesManager", () => ({
  getSpacesManager: () => ({ updateDefaultAssistantSkills })
}));

vi.mock("$app/navigation", () => ({
  afterNavigate: vi.fn(),
  beforeNavigate: vi.fn(),
  disableScrollHandling: vi.fn(),
  goto: vi.fn(),
  invalidate,
  invalidateAll: vi.fn(),
  onNavigate: vi.fn(),
  preloadCode: vi.fn(),
  preloadData: vi.fn(),
  pushState: vi.fn(),
  refreshAll: vi.fn(),
  replaceState: vi.fn()
}));

import SkillDetailPage from "./+page.svelte";

function revision(revisionNumber: number): SkillRevisionPublic {
  return {
    id: `revision-${revisionNumber}`,
    skill_id: "skill-1",
    revision_number: revisionNumber,
    display_name: `HR guidance ${revisionNumber}`,
    description: `Description ${revisionNumber}`,
    instructions: `Instructions ${revisionNumber}`,
    content_digest: String(revisionNumber).repeat(64),
    created_by_user_id: "user-1",
    created_at: `2026-07-${String(revisionNumber).padStart(2, "0")}T12:00:00Z`
  };
}

function revisionPage(
  current: SkillRevisionPublic,
  historical: SkillRevisionPublic
): SkillRevisionSummaryPage {
  return {
    items: [current, historical].map((item) => ({
      id: item.id,
      skill_id: item.skill_id,
      revision_number: item.revision_number,
      display_name: item.display_name,
      created_at: item.created_at
    })),
    count: 2,
    limit: 25,
    next_cursor: null,
    previous_cursor: null,
    total_count: 2
  };
}

function skill(currentRevision: SkillRevisionPublic): SkillPublic {
  return {
    id: currentRevision.skill_id,
    space_id: "space-1",
    slug: "hr-guidance",
    is_active: true,
    current_revision_id: currentRevision.id,
    current_revision_number: currentRevision.revision_number,
    display_name: currentRevision.display_name,
    description: currentRevision.description,
    content_digest: currentRevision.content_digest,
    created_by_user_id: "user-1",
    created_at: "2026-07-01T12:00:00Z",
    updated_at: currentRevision.created_at,
    current_revision: currentRevision
  };
}

describe("Skill detail page", () => {
  beforeEach(() => {
    invalidate.mockClear();
    updateDefaultAssistantSkills.mockReset();
  });

  const OTHER_SKILL = {
    skill_id: "skill-2",
    skill_revision_id: "skill-2-revision-1",
    attachable_revision_id: "skill-2-revision-1",
    slug: "minutes",
    revision_number: 1,
    attachable_revision_number: 1,
    display_name: "Minutes",
    description: "",
    content_digest: "digest",
    position: 1,
    is_active: true,
    source: "space" as const,
    execution_blocked: false,
    activation_mode: "always" as const
  };

  function personalChatOn(
    pinned: SkillRevisionPublic,
    latest: SkillRevisionPublic,
    others: AssistantSkillConfiguration["bindings"] = []
  ) {
    return {
      bindings: [
        {
          skill_id: pinned.skill_id,
          skill_revision_id: pinned.id,
          attachable_revision_id: latest.id,
          slug: "hr-guidance",
          revision_number: pinned.revision_number,
          attachable_revision_number: latest.revision_number,
          display_name: pinned.display_name,
          description: pinned.description,
          content_digest: pinned.content_digest,
          position: 0,
          is_active: true,
          source: "space",
          execution_blocked: false,
          activation_mode: "on_demand"
        },
        ...others
      ],
      organisation_bindings: [],
      runtime: null,
      personal_layer: { status: "applied", reason: null, detail: null }
    } satisfies AssistantSkillConfiguration;
  }

  /** The page was loaded with `loaded`; the server holds `saved` by the time the save runs. */
  function renderPersonalSkill({
    loaded = personalChatOn(revision(1), revision(2)),
    saved = loaded
  }: { loaded?: AssistantSkillConfiguration; saved?: AssistantSkillConfiguration } = {}) {
    const pinned = revision(1);
    const current = revision(2);
    const getAssistantConfiguration = vi.fn(async () => saved);
    render(SkillDetailPage, {
      data: {
        currentSpace: {
          id: "personal-space",
          personal: true,
          organization: false,
          skill_permissions: ["read", "edit"],
          default_assistant: { id: "default-assistant" }
        },
        skill: skill(current),
        revisionPage: revisionPage(current, pinned),
        personalChatSkills: loaded,
        eneo: {
          skills: {
            createRevision: vi.fn(),
            getAssistantConfiguration,
            getRevision: vi.fn(),
            listRevisionSummaries: vi.fn(),
            restoreRevision: vi.fn(),
            setActive: vi.fn()
          }
        }
      } as never
    });
    return { getAssistantConfiguration };
  }

  test("moves only this Skill to its latest version, on top of what is saved when the move runs", async () => {
    // Loaded with another Skill that an earlier queued save then switched off.
    const { getAssistantConfiguration } = renderPersonalSkill({
      loaded: personalChatOn(revision(1), revision(2), [OTHER_SKILL]),
      saved: personalChatOn(revision(1), revision(2))
    });

    await expect
      .element(page.getByText(m.personal_chat_skills_version_notice({ version: "1" })))
      .toBeVisible();
    expect(updateDefaultAssistantSkills).not.toHaveBeenCalled();
    await page.getByRole("button", { name: m.personal_chat_skills_use_latest() }).click();

    const [assistant, bindings] = updateDefaultAssistantSkills.mock.calls[0];
    expect(assistant).toEqual({ id: "default-assistant" });
    await expect(bindings()).resolves.toEqual([
      { skill_id: "skill-1", skill_revision_id: "revision-2", activation_mode: "on_demand" }
    ]);
    expect(getAssistantConfiguration).toHaveBeenCalledWith({
      spaceId: "personal-space",
      assistantId: "default-assistant"
    });
    await vi.waitFor(() => expect(invalidate).toHaveBeenCalledWith("space:skills"));
  });

  test("keeps the personal chat on its version and says why when the move is refused", async () => {
    updateDefaultAssistantSkills.mockRejectedValue(
      new EneoError("Refused", "RESPONSE", 400, 9080, {
        eneo_error_code: 9080,
        details: { reason: "personal_skill_does_not_fit", detail: "context_limit_exceeded" }
      })
    );
    renderPersonalSkill();

    await page.getByRole("button", { name: m.personal_chat_skills_use_latest() }).click();

    await expect
      .element(
        page
          .getByRole("alert")
          .getByText(m.personal_chat_skills_reason_personal_skill_does_not_fit())
      )
      .toBeVisible();
    expect(invalidate).not.toHaveBeenCalled();
  });

  test("keeps dirty form content and reloads the comparison after a restore conflict", async () => {
    const visibleCurrent = revision(2);
    const historical = revision(1);
    const newerCurrent = revision(3);
    const restoreRevision = vi.fn().mockRejectedValue(
      Object.assign(new Error("The Skill changed after you reviewed it."), {
        status: 409
      })
    );
    const get = vi.fn(async () => skill(newerCurrent));

    render(SkillDetailPage, {
      data: {
        currentSpace: {
          id: "space-1",
          personal: false,
          organization: false,
          skill_permissions: ["read", "edit"]
        },
        skill: skill(visibleCurrent),
        revisionPage: revisionPage(visibleCurrent, historical),
        eneo: {
          skills: {
            createRevision: vi.fn(),
            get,
            getRevision: vi.fn(async () => historical),
            listRevisionSummaries: vi.fn(),
            restoreRevision,
            setActive: vi.fn()
          }
        }
      } as never
    });

    const nameInput = page.getByLabelText(m.skills_display_name_label());
    await nameInput.fill("Unsaved editor draft");

    await page
      .getByRole("button", {
        name: m.skills_library_view_revision_aria({ revision: "1" })
      })
      .click();
    await page
      .getByRole("button", { name: m.skills_library_restore_revision_from_preview() })
      .click();
    await page.getByRole("button", { name: m.skills_library_restore_action() }).click();

    await vi.waitFor(() =>
      expect(restoreRevision).toHaveBeenCalledWith({
        spaceId: "space-1",
        skillId: "skill-1",
        sourceRevisionId: historical.id,
        reviewed_current_revision_id: visibleCurrent.id
      })
    );
    await vi.waitFor(() => expect(get).toHaveBeenCalledOnce());
    await expect.element(nameInput).toHaveValue("Unsaved editor draft");
    await expect.element(page.getByText(newerCurrent.instructions)).toBeVisible();
    await expect.element(page.getByText(historical.instructions)).toBeVisible();
    expect(invalidate).not.toHaveBeenCalled();
  });

  test("controls availability for new attachments without describing existing bindings as disabled", async () => {
    const current = revision(2);
    const setActive = vi.fn(async () => {});

    render(SkillDetailPage, {
      data: {
        currentSpace: {
          id: "space-1",
          personal: false,
          organization: false,
          skill_permissions: ["read", "edit"]
        },
        skill: skill(current),
        revisionPage: revisionPage(current, revision(1)),
        eneo: {
          skills: {
            createRevision: vi.fn(),
            getRevision: vi.fn(),
            listRevisionSummaries: vi.fn(),
            restoreRevision: vi.fn(),
            setActive
          }
        }
      } as never
    });

    const availability = page.getByRole("switch", {
      name: m.skills_library_availability_switch_label()
    });
    await expect.element(availability).toBeChecked();
    await availability.click();

    expect(setActive).toHaveBeenCalledWith({
      spaceId: "space-1",
      skillId: "skill-1",
      is_active: false
    });
    await vi.waitFor(() => expect(invalidate).toHaveBeenCalledWith("space:skills"));
    await expect.element(page.getByText(m.skills_library_inactive_explanation())).toBeVisible();
  });

  test("restores the availability switch when the update fails", async () => {
    const current = revision(2);
    const setActive = vi.fn(async () => {
      throw new Error("Temporary failure");
    });

    render(SkillDetailPage, {
      data: {
        currentSpace: {
          id: "space-1",
          personal: false,
          organization: false,
          skill_permissions: ["read", "edit"]
        },
        skill: skill(current),
        revisionPage: revisionPage(current, revision(1)),
        eneo: {
          skills: {
            createRevision: vi.fn(),
            getRevision: vi.fn(),
            listRevisionSummaries: vi.fn(),
            restoreRevision: vi.fn(),
            setActive
          }
        }
      } as never
    });

    const availability = page.getByRole("switch", {
      name: m.skills_library_availability_switch_label()
    });
    await availability.click();

    // A thrown Error is a bug or a network failure; its raw text is developer
    // English. The user gets the localized message for what they were doing.
    await expect.element(page.getByText(m.skills_library_status_error())).toBeVisible();
    await expect
      .element(page.getByText("Temporary failure", { exact: true }))
      .not.toBeInTheDocument();
    await expect.element(availability).toBeChecked();
  });
});
