"use client";

import { useTranslations } from "next-intl";
import { useState } from "react";
import { SettingsGroup, SettingsRow } from "@/components/composites/settings-rows";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { useSpace } from "@/features/spaces/use-space";
import type { App } from "../apps";
import { useUpdateApp } from "./use-app";

/** Conversation retention; empty inherits the space policy. */
export function SecuritySection({ app }: { app: App }) {
  const t = useTranslations();
  const { space } = useSpace();
  const update = useUpdateApp(app.id);

  const saved = app.data_retention_days?.toString() ?? "";
  const [days, setDays] = useState(saved);
  const dirty = days !== saved;

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
