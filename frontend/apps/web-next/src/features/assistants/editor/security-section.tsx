"use client";

import { useTranslations } from "next-intl";
import { useState } from "react";
import { SettingsGroup, SettingsRow } from "@/components/composites/settings-rows";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { useSpace } from "@/features/spaces/use-space";
import { useUpdateAssistant, type Assistant } from "./use-assistant";

/** Conversation retention; empty inherits the space policy. */
export function SecuritySection({ assistant }: { assistant: Assistant }) {
  const t = useTranslations();
  const { space } = useSpace();
  const update = useUpdateAssistant(assistant.id);

  const saved = assistant.data_retention_days?.toString() ?? "";
  const [days, setDays] = useState(saved);
  const dirty = days !== saved;

  const inherited = space.data_retention_days ? `${space.data_retention_days} ${t("days")}` : "∞";

  return (
    <SettingsGroup title={t("security_and_privacy")}>
      <SettingsRow
        title={t("conversation_retention_title")}
        description={t("conversation_retention_assistant_description")}
      >
        <div className="flex items-center gap-2">
          <Label htmlFor="assistant-retention-days" className="sr-only">
            {t("conversation_retention_title")}
          </Label>
          <Input
            id="assistant-retention-days"
            type="number"
            min={1}
            className="w-32"
            value={days}
            placeholder={inherited}
            onChange={(event) => setDays(event.target.value)}
          />
          <span className="text-muted-foreground text-sm">{t("days")}</span>
          {dirty && (
            <Button
              size="sm"
              disabled={update.isPending}
              onClick={() =>
                update.mutate({ data_retention_days: days === "" ? null : Number(days) })
              }
            >
              {update.isPending ? t("loading") : t("save_changes")}
            </Button>
          )}
        </div>
      </SettingsRow>
    </SettingsGroup>
  );
}
