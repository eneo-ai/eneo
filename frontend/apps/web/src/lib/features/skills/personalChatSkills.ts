import {
  EneoError,
  type AssistantSkillBindingInput,
  type AssistantSkillBindingSummary,
  type AssistantSkillConfiguration,
  type Eneo,
  type EneoErrorCode,
  type SkillActivationMode,
  type SkillSparse
} from "@eneo/eneo-js";
import { m } from "$lib/paraglide/messages";
import {
  appendSkillRevisionBinding,
  removeSkillBinding,
  setSkillActivationMode,
  upgradeSkillBinding
} from "./skillBindings";

/** "Off" is not a mode the backend knows: the Skill is left out of the list. */
export type PersonalSkillMode = SkillActivationMode | "off";

type PersonalSkillLayer = NonNullable<AssistantSkillConfiguration["personal_layer"]>;
type PersonalSkillLayerReason = NonNullable<PersonalSkillLayer["reason"]>;

const PERSONAL_SKILLS_REJECTED: EneoErrorCode = 9080;
// The backend's largest Skill catalogue page.
const LIBRARY_PAGE_LIMIT = 100;

const LAYER_REASON_MESSAGES: Record<PersonalSkillLayerReason, () => string> = {
  permission_missing: () => m.personal_chat_skills_reason_permission_missing(),
  attachment_limit_exceeded: () => m.personal_chat_skills_reason_attachment_limit_exceeded(),
  model_context_exceeded: () => m.personal_chat_skills_reason_model_context_exceeded(),
  on_demand_unavailable: () => m.personal_chat_skills_reason_on_demand_unavailable(),
  personal_skill_does_not_fit: () => m.personal_chat_skills_reason_personal_skill_does_not_fit(),
  organisation_skill_crowded_out: () =>
    m.personal_chat_skills_reason_organisation_skill_crowded_out()
};

/**
 * The person's own Skills as the Assistant update takes them: the full
 * ordered list, each at the exact revision it is pinned to.
 */
export function personalSkillBindings(
  bindings: AssistantSkillBindingSummary[]
): AssistantSkillBindingInput[] {
  return [...bindings]
    .sort((a, b) => a.position - b.position)
    .map(({ skill_id, skill_revision_id, activation_mode }) => ({
      skill_id,
      skill_revision_id,
      activation_mode
    }));
}

/**
 * A Skill joins at the revision the person sees now; one already in the chat
 * keeps its pinned revision until they choose the latest one.
 */
export function withPersonalSkillMode(
  bindings: AssistantSkillBindingInput[],
  skill: { id: string; revisionId: string },
  mode: PersonalSkillMode
): AssistantSkillBindingInput[] {
  if (mode === "off") return removeSkillBinding(bindings, skill.id);
  return bindings.some((binding) => binding.skill_id === skill.id)
    ? setSkillActivationMode(bindings, skill.id, mode)
    : appendSkillRevisionBinding(bindings, skill, mode);
}

export type OwnSkillRow = {
  id: string;
  name: string;
  description: string;
  /** Where a Skill joining the chat starts: its current revision. */
  revisionId: string;
  mode: PersonalSkillMode;
  /** The saved binding: its pinned and newest revision and any block. */
  binding: AssistantSkillBindingSummary | undefined;
  hasNewerRevision: boolean;
};

/**
 * One row per own Skill, in library order, showing the chosen `bindings`
 * (the change being saved, or the saved list). Without the library, which is
 * only read for a person who may choose, the saved Skills are all there is.
 */
export function personalSkillRows(
  saved: AssistantSkillBindingSummary[],
  library: SkillSparse[] | null,
  bindings: AssistantSkillBindingInput[]
): OwnSkillRow[] {
  const savedById = new Map(saved.map((binding) => [binding.skill_id, binding]));
  const chosenById = new Map(bindings.map((binding) => [binding.skill_id, binding]));
  const skills = library
    ? library
        // A deactivated Skill cannot join the chat, but keeps running in it.
        .filter((skill) => skill.is_active || savedById.has(skill.id) || chosenById.has(skill.id))
        .map((skill) => ({
          id: skill.id,
          name: skill.display_name,
          description: skill.description,
          revisionId: skill.current_revision_id
        }))
    : saved.map((binding) => ({
        id: binding.skill_id,
        name: binding.display_name,
        description: binding.description,
        revisionId: binding.skill_revision_id
      }));
  return skills.map((skill) => {
    const binding = savedById.get(skill.id);
    const choice = chosenById.get(skill.id);
    return {
      ...skill,
      mode: choice?.activation_mode ?? "off",
      binding,
      hasNewerRevision:
        !!binding && !!choice && personalSkillHasNewerRevision(binding, choice.skill_revision_id)
    };
  });
}

/** Whether the chat is pinned to an older revision than the one it may move to. */
export function personalSkillHasNewerRevision(
  binding: AssistantSkillBindingSummary,
  pinnedRevisionId = binding.skill_revision_id
): boolean {
  return !!binding.attachable_revision_id && binding.attachable_revision_id !== pinnedRevisionId;
}

/** "Använd senaste versionen": one Skill moves; the rest stay as saved. */
export function withLatestPersonalSkillRevision(
  bindings: AssistantSkillBindingInput[],
  binding: AssistantSkillBindingSummary
): AssistantSkillBindingInput[] {
  if (!binding.attachable_revision_id) return bindings;
  return upgradeSkillBinding(
    bindings,
    bindings.findIndex((reference) => reference.skill_id === binding.skill_id),
    {
      id: binding.skill_id,
      attachableRevisionId: binding.attachable_revision_id,
      isActive: binding.is_active
    }
  );
}

/**
 * Skills that run in the personal chat, per mode: the organisation's unless
 * blocked, and the person's own unless blocked or paused.
 */
export function runningPersonalChatSkills(
  configuration: AssistantSkillConfiguration
): Record<SkillActivationMode, number> {
  const own = configuration.personal_layer?.status === "suspended" ? [] : configuration.bindings;
  const running = [...(configuration.organisation_bindings ?? []), ...own].filter(
    (binding) => !binding.execution_blocked
  );
  return {
    always: running.filter((binding) => binding.activation_mode === "always").length,
    on_demand: running.filter((binding) => binding.activation_mode === "on_demand").length
  };
}

export function activationModeLabel(mode: PersonalSkillMode): string {
  switch (mode) {
    case "always":
      return m.skills_activation_mode_always();
    case "on_demand":
      return m.skills_activation_mode_on_demand();
    case "off":
      return m.personal_chat_skills_mode_off();
  }
}

/** Why the person's own Skills do not run, or would not with a change. */
export function personalSkillLayerMessage({
  reason,
  detail
}: Pick<PersonalSkillLayer, "reason" | "detail">): string {
  if (reason === "on_demand_unavailable" && detail === "selective_activation_disabled") {
    return m.personal_chat_skills_reason_on_demand_disabled();
  }
  return reason && reason in LAYER_REASON_MESSAGES
    ? LAYER_REASON_MESSAGES[reason]()
    : m.personal_chat_skills_save_failed();
}

export function personalSkillsSaveErrorMessage(error: unknown): string {
  if (error instanceof EneoError) {
    if (error.code === PERSONAL_SKILLS_REJECTED) {
      return personalSkillLayerMessage(error.response?.details ?? {});
    }
    if (error.status === 403) return m.personal_chat_skills_reason_permission_missing();
  }
  return m.personal_chat_skills_save_failed();
}

/** Every Skill in the person's own space, which is all they may choose from. */
export async function listPersonalSpaceSkills(eneo: Eneo, spaceId: string): Promise<SkillSparse[]> {
  const skills: SkillSparse[] = [];
  let cursor: string | null = null;
  do {
    const page = await eneo.skills.list({ spaceId, limit: LIBRARY_PAGE_LIMIT, cursor });
    skills.push(...page.items);
    cursor = page.next_cursor ?? null;
  } while (cursor);
  return skills;
}

/**
 * The personal chat's Skill configuration for the personal space's Skills
 * pages, or null anywhere else. These pages only show it beside the
 * library, so a failed read leaves the library usable rather than failing it.
 */
export function loadPersonalChatSkillConfiguration(
  eneo: Eneo,
  space: { id: string; personal: boolean; default_assistant?: { id: string } | null }
): Promise<AssistantSkillConfiguration | null> {
  const assistant = space.personal ? space.default_assistant : null;
  if (!assistant) return Promise.resolve(null);
  return eneo.skills
    .getAssistantConfiguration({ spaceId: space.id, assistantId: assistant.id })
    .catch(() => null);
}
