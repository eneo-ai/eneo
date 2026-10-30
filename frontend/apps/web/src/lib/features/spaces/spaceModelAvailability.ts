import type { CompletionModel, TranscriptionModel } from "@eneo/eneo-js";
import type { LinkedModelRow } from "$lib/features/ai-models/linkedModelRow";

type CompletionModelAvailability = Pick<CompletionModel, "can_access">;
type TranscriptionModelAvailability = Pick<TranscriptionModel, "can_access">;
type SpaceModelAvailability = {
  completion_models: readonly CompletionModelAvailability[];
  transcription_models: readonly TranscriptionModelAvailability[];
};

export function hasAccessibleCompletionModel(
  models: readonly CompletionModelAvailability[] | null | undefined
): boolean {
  return models?.some((model) => model.can_access === true) ?? false;
}

export function hasAccessibleTranscriptionModel(
  models: readonly TranscriptionModelAvailability[] | null | undefined
): boolean {
  return models?.some((model) => model.can_access === true) ?? false;
}

export function spaceCanCreateApps(space: SpaceModelAvailability): boolean {
  return (
    hasAccessibleCompletionModel(space.completion_models) &&
    hasAccessibleTranscriptionModel(space.transcription_models)
  );
}

type ModelKind = "completion" | "embedding" | "transcription";

/** One linked model and the state of its link, as the space reports it. */
export type SpaceModelLinkState = {
  id: string;
  name: string;
  nickname?: string | null;
  meets_security_classification: boolean;
  available: boolean;
};
type LinkedSpaceModels = {
  linked_models?: Partial<Record<`${ModelKind}_models`, readonly SpaceModelLinkState[]>>;
};

/** The links of a kind as the space reports them, or null when the space did
 *  not report them. A save of the space's model list adds and removes links
 *  against these, so an editor without them must not save. */
export function spaceModelLinks(
  space: LinkedSpaceModels,
  kind: ModelKind
): readonly SpaceModelLinkState[] | null {
  return space.linked_models?.[`${kind}_models`] ?? null;
}

/** Every model of a kind linked to the space, usable or not: those below the
 *  space's security classification and those the tenant disabled too. A save
 *  of the space's model list sends these IDs, so a toggle can never drop a
 *  link the page does not show as usable. Null when the state is missing. */
export function linkedSpaceModelIds(space: LinkedSpaceModels, kind: ModelKind): string[] | null {
  return spaceModelLinks(space, kind)?.map((link) => link.id) ?? null;
}

type SettingsModel = {
  id: string;
  is_org_enabled?: boolean | null;
  is_deprecated?: boolean | null;
  migrated_to_model_id?: string | null;
};

/** The rows of a space's model settings: every model an admin may add, plus
 *  every linked model whatever its state, so each link can be switched off.
 *  A linked model the catalogue does not list gets a row built from its link. */
export function spaceSettingsModelRows<T extends SettingsModel>(
  models: readonly T[],
  links: readonly SpaceModelLinkState[]
): (T | LinkedModelRow)[] {
  const linked = new Set(links.map((link) => link.id));
  const rows = models.filter(
    (model) =>
      linked.has(model.id) ||
      (model.is_org_enabled && !model.is_deprecated && !model.migrated_to_model_id)
  );
  const listed = new Set(models.map((model) => model.id));
  const fallback = links
    .filter((link) => !listed.has(link.id))
    .map((link): LinkedModelRow => ({
      link_only: true,
      id: link.id,
      name: link.name,
      nickname: link.nickname ?? null,
      is_org_enabled: link.available,
      meets_security_classification: link.meets_security_classification,
      org: null,
      provider_name: null,
      provider_type: null
    }));
  return [...rows, ...fallback];
}
