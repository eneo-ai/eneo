"use client";

import { useTranslations } from "use-intl";
import { useState } from "react";
import { FieldProblem, fieldProblemProps } from "@/components/composites/field-problem";
import { SettingsGroup, SettingsRow } from "@/components/composites/settings-rows";
import { useAutosaveField } from "@/components/composites/use-autosave";
import { Input } from "@/components/ui/input";
import { parseRetentionDays } from "@/features/spaces/retention-days";
import { useSpace } from "@/features/spaces/use-space";
import type { App } from "../apps";
import { useUpdateApp } from "./use-app";

/** Conversation retention; empty inherits the space policy. */
export function SecuritySection({ app }: { app: App }) {
  const t = useTranslations();
  const { space } = useSpace();
  const update = useUpdateApp(app.id);
  const [daysVisited, setDaysVisited] = useState(false);

  const days = useAutosaveField({
    key: "app-retention-days",
    value: app.data_retention_days?.toString() ?? "",
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
        description={t("conversation_retention_app_description")}
        htmlFor="app-retention-days"
      >
        <div className="flex items-center gap-2">
          <Input
            id="app-retention-days"
            // Text, not number: a number input reports a half-typed "1e" as
            // empty, which would save as "inherit".
            type="text"
            inputMode="numeric"
            className="w-32"
            value={days.value}
            placeholder={inherited}
            onChange={(event) => days.setValue(event.target.value)}
            onBlur={() => {
              setDaysVisited(true);
              void days.commit();
            }}
            {...fieldProblemProps("app-retention-days", daysProblem)}
          />
          <span className="text-muted-foreground text-sm">{t("days")}</span>
        </div>
        <FieldProblem id="app-retention-days" problem={daysProblem} />
      </SettingsRow>
    </SettingsGroup>
  );
}
