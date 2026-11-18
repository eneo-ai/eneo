import { createContext, useContext } from "react";
import { currentSetting, sameSetting, type SettingChange } from "./assistant-helper-changes";
import type { Assistant } from "./use-assistant";

/**
 * What the helper chat's cards need from the settings form beside them: to
 * save what the form has pending before a card saves, and to mark what a
 * card's save changed. The editor provides it; a card without it saves as it
 * is and says only that it saved.
 */

/** Who changed the settings: the helper's own tool, or the person with "Använd" or "Ångra". */
export type ChangeOrigin = "helper" | "applied" | "undone";

export type AssistantHelperForm = {
  /** Saves every draft the form has not saved, and waits for saves on their way: false when one failed. */
  savePending: () => Promise<boolean>;
  /** Marks the settings that changed in the form for a while and says so, naming them. */
  showChanges: (fields: readonly string[], origin: ChangeOrigin) => void;
};

const AssistantHelperFormContext = createContext<AssistantHelperForm | null>(null);

export const AssistantHelperFormProvider = AssistantHelperFormContext.Provider;

export function useAssistantHelperForm(): AssistantHelperForm | null {
  return useContext(AssistantHelperFormContext);
}

/**
 * The settings a call of the helper actually changed, each once: a value it
 * gives as before and after alike changed nothing; a text too long to show
 * changed, as the call says.
 */
export function changedFields(changes: readonly SettingChange[]): string[] {
  const fields = changes
    .filter((change) => change.tooLong || !sameSetting(change.field, change.before, change.after))
    .map((change) => change.field);
  return [...new Set(fields)];
}

/** The settings among `fields` whose values differ between two readings of the assistant. */
export function fieldsChangedBetween(
  fields: readonly string[],
  before: Assistant,
  after: Assistant
): string[] {
  return [...new Set(fields)].filter(
    (field) => !sameSetting(field, currentSetting(before, field), currentSetting(after, field))
  );
}
