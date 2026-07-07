"use client";

import { useTranslations } from "next-intl";
import { SettingsGroup, SettingsRow } from "@/components/composites/settings-rows";
import { useAutosaveField } from "@/components/composites/use-autosave";
import { Input } from "@/components/ui/input";
import { useSpace } from "@/features/spaces/use-space";
import { useUpdateAssistant, type Assistant } from "./use-assistant";

/** Conversation retention; empty inherits the space policy. */
export function SecuritySection({ assistant }: { assistant: Assistant }) {
  const t = useTranslations();
  const { space } = useSpace();
  const update = useUpdateAssistant(assistant.id);

  const days = useAutosaveField({
    key: "assistant-retention-days",
    value: assistant.data_retention_days?.toString() ?? "",
    save: (value) =>
      update.mutateAsync({ data_retention_days: value === "" ? null : Number(value) }),
    // Empty inherits the space policy; otherwise require a positive whole number.
    validate: (value) => value === "" || (Number.isInteger(Number(value)) && Number(value) >= 1)
  });

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
            className="w-32"
            value={days.value}
            placeholder={inherited}
            onChange={(event) => days.setValue(event.target.value)}
            onBlur={() => days.commit()}
          />
          <span className="text-muted-foreground text-sm">{t("days")}</span>
        </div>
      </SettingsRow>
    </SettingsGroup>
  );
}
