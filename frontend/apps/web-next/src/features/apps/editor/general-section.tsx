"use client";

import { useTranslations } from "next-intl";
import { IconField } from "@/components/composites/icon-field";
import { SettingsGroup, SettingsRow } from "@/components/composites/settings-rows";
import { useAutosaveField } from "@/components/composites/use-autosave";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import type { App } from "../apps";
import { useUpdateApp } from "./use-app";

export function GeneralSection({ app }: { app: App }) {
  const t = useTranslations();
  const update = useUpdateApp(app.id);

  const name = useAutosaveField({
    key: "general",
    value: app.name,
    save: (value) => update.mutateAsync({ name: value }),
    normalize: (value) => value.trim()
  });
  const description = useAutosaveField({
    key: "general",
    value: app.description ?? "",
    save: (value) => update.mutateAsync({ description: value })
  });

  return (
    <SettingsGroup title={t("general")}>
      <SettingsRow title={t("name")} description={t("app_name_description")} htmlFor="app-name">
        <Input
          id="app-name"
          value={name.value}
          onChange={(event) => name.setValue(event.target.value)}
          // An app must keep a name — revert an emptied field on blur.
          onBlur={() => (name.value.trim() ? name.commit() : name.reset())}
        />
      </SettingsRow>
      <SettingsRow
        title={t("description")}
        description={t("app_description_description")}
        htmlFor="app-description"
      >
        <Textarea
          id="app-description"
          value={description.value}
          rows={4}
          onChange={(event) => description.setValue(event.target.value)}
          onBlur={() => description.commit()}
        />
      </SettingsRow>
      <SettingsRow title={t("avatar")} description={t("avatar_description")}>
        <IconField
          iconId={app.icon_id}
          onSave={(iconId) => update.mutateAsync({ icon_id: iconId })}
        />
      </SettingsRow>
    </SettingsGroup>
  );
}
