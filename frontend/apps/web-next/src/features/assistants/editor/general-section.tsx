"use client";

import { useTranslations } from "next-intl";
import { useState } from "react";
import { IconField } from "@/components/composites/icon-field";
import { SettingsGroup, SettingsRow } from "@/components/composites/settings-rows";
import { useReportDirty } from "@/components/composites/save-status";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { useUpdateAssistant, type Assistant } from "./use-assistant";

export function SaveRow({
  dirty,
  pending,
  onSave,
  onRevert
}: {
  dirty: boolean;
  pending: boolean;
  onSave: () => void;
  onRevert: () => void;
}) {
  const t = useTranslations();
  if (!dirty) return null;
  return (
    <div className="flex justify-end gap-2">
      <Button variant="outline" size="sm" disabled={pending} onClick={onRevert}>
        {t("cancel")}
      </Button>
      <Button size="sm" disabled={pending} onClick={onSave}>
        {pending ? t("loading") : t("save_changes")}
      </Button>
    </div>
  );
}

export function GeneralSection({ assistant }: { assistant: Assistant }) {
  const t = useTranslations();
  const update = useUpdateAssistant(assistant.id);
  const [name, setName] = useState(assistant.name);
  const [description, setDescription] = useState(assistant.description ?? "");

  const dirty = name !== assistant.name || description !== (assistant.description ?? "");
  useReportDirty("general", dirty);

  return (
    <SettingsGroup title={t("general")}>
      <SettingsRow
        title={t("name")}
        description={t("assistant_name_description")}
        htmlFor="assistant-name"
      >
        <Input id="assistant-name" value={name} onChange={(event) => setName(event.target.value)} />
      </SettingsRow>
      <SettingsRow
        title={t("description")}
        description={t("assistant_description_description")}
        htmlFor="assistant-description"
      >
        <Textarea
          id="assistant-description"
          value={description}
          rows={4}
          placeholder={t("assistant_placeholder", { name })}
          onChange={(event) => setDescription(event.target.value)}
        />
        <SaveRow
          dirty={dirty}
          pending={update.isPending}
          onSave={() => update.mutate({ name: name.trim(), description })}
          onRevert={() => {
            setName(assistant.name);
            setDescription(assistant.description ?? "");
          }}
        />
      </SettingsRow>
      <SettingsRow title={t("avatar")} description={t("avatar_description")}>
        <IconField
          iconId={assistant.icon_id}
          onSave={(iconId) => update.mutateAsync({ icon_id: iconId })}
        />
      </SettingsRow>
    </SettingsGroup>
  );
}
