"use client";

import { useTranslations } from "next-intl";
import { useState } from "react";
import { IconField } from "@/components/composites/icon-field";
import { SettingsGroup, SettingsRow } from "@/components/composites/settings-rows";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { SaveRow } from "@/features/assistants/editor/general-section";
import type { App } from "../apps";
import { useUpdateApp } from "./use-app";

export function GeneralSection({ app }: { app: App }) {
  const t = useTranslations();
  const update = useUpdateApp(app.id);
  const [name, setName] = useState(app.name);
  const [description, setDescription] = useState(app.description ?? "");

  const dirty = name !== app.name || description !== (app.description ?? "");

  return (
    <SettingsGroup title={t("general")}>
      <SettingsRow title={t("name")} description={t("app_name_description")}>
        <Input value={name} onChange={(event) => setName(event.target.value)} />
      </SettingsRow>
      <SettingsRow title={t("description")} description={t("app_description_description")}>
        <Textarea
          value={description}
          rows={4}
          onChange={(event) => setDescription(event.target.value)}
        />
        <SaveRow
          dirty={dirty}
          pending={update.isPending}
          onSave={() => update.mutate({ name: name.trim(), description })}
          onRevert={() => {
            setName(app.name);
            setDescription(app.description ?? "");
          }}
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
