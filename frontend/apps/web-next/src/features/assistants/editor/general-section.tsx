"use client";

import { useTranslations } from "next-intl";
import { useEffect, useRef } from "react";
import { IconField } from "@/components/composites/icon-field";
import { SettingsGroup, SettingsRow } from "@/components/composites/settings-rows";
import { useAutosaveField } from "@/components/composites/use-autosave";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { useUpdateAssistant, type Assistant } from "./use-assistant";

export function GeneralSection({
  assistant,
  focusName = false
}: {
  assistant: Assistant;
  /**
   * The editor opened right after the assistant was created with a default
   * name: focus the name field with that name selected, so typing replaces it.
   * Carries on the user's own action, like the name dialog it replaced.
   */
  focusName?: boolean;
}) {
  const t = useTranslations();
  const update = useUpdateAssistant(assistant.id);
  const nameRef = useRef<HTMLInputElement>(null);

  const name = useAutosaveField({
    key: "assistant-name",
    value: assistant.name,
    save: (value) => update.mutateAsync({ name: value }),
    normalize: (value) => value.trim(),
    validate: (value) => value.length > 0
  });
  const description = useAutosaveField({
    key: "assistant-description",
    value: assistant.description ?? "",
    save: (value) => update.mutateAsync({ description: value })
  });

  useEffect(() => {
    if (!focusName) return;
    nameRef.current?.focus();
    nameRef.current?.select();
  }, [focusName]);

  return (
    <SettingsGroup title={t("general")}>
      <SettingsRow
        title={t("name")}
        description={t("assistant_name_description")}
        htmlFor="assistant-name"
      >
        <Input
          ref={nameRef}
          id="assistant-name"
          value={name.value}
          onChange={(event) => name.setValue(event.target.value)}
          // An assistant must keep a name — revert an emptied field on blur.
          onBlur={() => (name.value.trim() ? name.commit() : name.reset())}
        />
      </SettingsRow>
      <SettingsRow
        title={t("description")}
        description={t("assistant_description_description")}
        htmlFor="assistant-description"
      >
        <Textarea
          id="assistant-description"
          value={description.value}
          rows={4}
          placeholder={t("assistant_placeholder", { name: name.value })}
          onChange={(event) => description.setValue(event.target.value)}
          onBlur={() => description.commit()}
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
