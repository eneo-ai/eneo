"use client";

import { useId, useState } from "react";
import { useTranslations } from "next-intl";
import { FieldProblem, fieldProblemProps } from "@/components/composites/field-problem";
import { SettingsGroup, SettingsRow } from "@/components/composites/settings-rows";
import { useAutosaveField } from "@/components/composites/use-autosave";
import { Input } from "@/components/ui/input";
import { parseRetentionDays, RETENTION_MAX_DAYS } from "@/features/spaces/retention-days";
import { useSpace } from "@/features/spaces/use-space";
import { useUpdateAssistant, type Assistant } from "./use-assistant";

/**
 * Conversation retention; empty inherits the space policy. In a shared or
 * organisation space only those who may edit the space change it (the
 * backend refuses other editors); everyone else reads the value.
 */
export function SecuritySection({ assistant }: { assistant: Assistant }) {
  const t = useTranslations();
  const { space, can } = useSpace();
  const update = useUpdateAssistant(assistant.id);
  const readOnlyHintId = useId();
  const canEditRetention = space.personal || can("edit", "space");
  const [daysVisited, setDaysVisited] = useState(false);

  const days = useAutosaveField({
    key: "assistant-retention-days",
    value: assistant.data_retention_days?.toString() ?? "",
    save: (value) => update.mutateAsync({ data_retention_days: parseRetentionDays(value) }),
    // Empty inherits the space policy.
    validate: (value) => parseRetentionDays(value) !== undefined
  });
  const daysProblem =
    daysVisited && parseRetentionDays(days.value) === undefined
      ? t("conversation_retention_invalid")
      : null;

  const inherited = space.data_retention_days ? `${space.data_retention_days} ${t("days")}` : "∞";

  return (
    <SettingsGroup title={t("security_and_privacy")}>
      <SettingsRow
        title={t("conversation_retention_title")}
        description={t("conversation_retention_assistant_description")}
        htmlFor="assistant-retention-days"
      >
        <div className="flex items-center gap-2">
          <Input
            id="assistant-retention-days"
            type="number"
            min={1}
            max={RETENTION_MAX_DAYS}
            className="w-32"
            value={days.value}
            placeholder={inherited}
            onChange={(event) => days.setValue(event.target.value)}
            onBlur={() => {
              setDaysVisited(true);
              void days.commit();
            }}
            disabled={!canEditRetention}
            {...fieldProblemProps(
              "assistant-retention-days",
              daysProblem,
              canEditRetention ? undefined : readOnlyHintId
            )}
          />
          <span className="text-muted-foreground text-sm">{t("days")}</span>
        </div>
        <FieldProblem id="assistant-retention-days" problem={daysProblem} />
        {!canEditRetention && (
          <p id={readOnlyHintId} className="text-muted-foreground text-sm">
            {t("conversation_retention_space_admin_only")}
          </p>
        )}
      </SettingsRow>
    </SettingsGroup>
  );
}
