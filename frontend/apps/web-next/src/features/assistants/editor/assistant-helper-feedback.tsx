import { Banner } from "@astryxdesign/core/Banner";
import { useAnnounce } from "@astryxdesign/core/hooks";
import { useFormatter, useTranslations } from "use-intl";
import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { capabilityControlId } from "./assistant-editor-rules";
import { settingLabel } from "./assistant-helper-cards";
import { FUNCTION_FIELD_PREFIX } from "./assistant-helper-changes";
import type { ChangeOrigin } from "./assistant-helper-form";
import { modelSettingsMarkKey } from "./model-kwargs-rows";
import type { AssistantSectionId, SettingReference } from "./setting-references";

/**
 * What the form shows of the helper chat's work: the settings a change from
 * the chat touched, marked for a while, and the lock while the helper may
 * write.
 */

/** How long the marks stay: as long as the flow page's. */
export const CHAT_CHANGE_MARK_MS = 8000;

/** The form's rows to mark, by their key (see `SettingsMarks`), and how many settings changed per section. */
export type ChatChangeMarks = {
  rows: ReadonlySet<string>;
  sections: ReadonlyMap<AssistantSectionId, number>;
};

type References = ReadonlyMap<string, SettingReference>;

/**
 * The settings the form shows under another setting's reference: the
 * temperature is the behaviour's, the knowledge lists are the knowledge's,
 * the tool settings are the MCP servers'.
 */
const SHOWN_UNDER: Record<string, string> = {
  "completion_model_kwargs.temperature": "completion_model_kwargs",
  groups: "knowledge",
  websites: "knowledge",
  integration_knowledge_list: "knowledge",
  mcp_tools: "mcp_servers"
};

/** The function a field names on its own (`enabled_capabilities.<purpose>`); null for any other field. */
const functionOf = (field: string) =>
  field.startsWith(FUNCTION_FIELD_PREFIX) ? field.slice(FUNCTION_FIELD_PREFIX.length) : null;

/** The reference a changed setting is shown under: a function is the functions'. */
function referenceOf(field: string, references: References): SettingReference | undefined {
  if (functionOf(field) !== null) return references.get("enabled_capabilities");
  return references.get(SHOWN_UNDER[field] ?? field);
}

/**
 * The key of the row that shows a changed setting: a function's own row,
 * one row for the model's own settings, else its reference's control.
 */
function rowOf(field: string, reference: SettingReference): string | undefined {
  const purpose = functionOf(field);
  if (purpose !== null) return capabilityControlId(purpose);
  return reference.key.startsWith("completion_model_kwargs.")
    ? modelSettingsMarkKey("assistant")
    : reference.control;
}

/**
 * The rows and section counts for the settings that changed. A setting the
 * form does not show this person (a section not listed, a model setting the
 * model does not offer) is neither marked nor counted.
 */
export function chatChangeMarks(fields: Iterable<string>, references: References): ChatChangeMarks {
  const rows = new Set<string>();
  const counted = new Map<AssistantSectionId, Set<string>>();
  for (const field of fields) {
    const reference = referenceOf(field, references);
    if (!reference) continue;
    const row = rowOf(field, reference);
    if (row) rows.add(row);
    const section = counted.get(reference.section) ?? new Set<string>();
    section.add(field);
    counted.set(reference.section, section);
  }
  return {
    rows,
    sections: new Map([...counted].map(([section, settings]) => [section, settings.size]))
  };
}

/** The sentence that says what changed, by who changed it. */
const ANNOUNCEMENT_KEYS: Record<ChangeOrigin, string> = {
  helper: "helper_marks_changed_by_helper",
  applied: "helper_marks_applied",
  undone: "helper_marks_undone"
};

/**
 * The marks for changes from the chat. `show` marks the settings that
 * changed (with those still marked from a moment ago) and says once,
 * politely, which they are; the marks go `CHAT_CHANGE_MARK_MS` after the
 * last change. The person's own typing in the form never gets here.
 */
export function useChatChangeMarks(references: References) {
  const t = useTranslations();
  const format = useFormatter();
  const announce = useAnnounce();
  const [fields, setFields] = useState<ReadonlySet<string> | null>(null);
  useEffect(() => {
    if (!fields) return;
    const timer = window.setTimeout(() => setFields(null), CHAT_CHANGE_MARK_MS);
    return () => window.clearTimeout(timer);
  }, [fields]);

  const marks = useMemo(
    () => (fields ? chatChangeMarks(fields, references) : null),
    [fields, references]
  );
  const show = useCallback(
    (changed: readonly string[], origin: ChangeOrigin) => {
      if (changed.length === 0) return;
      // A function by its own name; any other setting as its reference names it.
      const labels = new Set(
        changed.map((field) =>
          functionOf(field) !== null
            ? settingLabel(field, t)
            : (referenceOf(field, references)?.label ?? settingLabel(field, t))
        )
      );
      announce(
        t(ANNOUNCEMENT_KEYS[origin], {
          settings: format.list([...labels], { type: "conjunction" })
        })
      );
      setFields((current) => new Set([...(current ?? []), ...changed]));
    },
    [announce, format, references, t]
  );
  return { marks, show };
}

/**
 * The form's lock while the helper may write it: said politely when it
 * starts and when it ends, and the notice to show above the form while it
 * lasts. The notice describes a state, so it has no live role.
 */
export function useHelperFormLock(locked: boolean): ReactNode {
  const t = useTranslations();
  const announce = useAnnounce();
  const announced = useRef(locked);
  useEffect(() => {
    if (announced.current === locked) return;
    announced.current = locked;
    announce(t(locked ? "helper_lock_started" : "helper_lock_ended"));
  }, [announce, locked, t]);
  return locked ? (
    <Banner
      status="info"
      title={t("helper_lock_title")}
      description={t("helper_lock_description")}
    />
  ) : null;
}
