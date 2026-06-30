"use client";

import { useTranslations } from "next-intl";
import { SettingsGroup, SettingsRow } from "@/components/composites/settings-rows";
import { useAutosaveField } from "@/components/composites/use-autosave";
import { Textarea } from "@/components/ui/textarea";
import type { App } from "../apps";
import { useUpdateApp } from "./use-app";

/**
 * App prompt. Prompt version history (PromptVersionDialog) is deferred, like
 * the assistant editor; tracked in the migration ledger.
 */
export function InstructionsSection({ app }: { app: App }) {
  const t = useTranslations();
  const update = useUpdateApp(app.id);

  const prompt = useAutosaveField({
    key: "instructions",
    value: app.prompt?.text ?? "",
    save: (value) => update.mutateAsync({ prompt: { text: value } })
  });

  return (
    <SettingsGroup title={t("instructions")}>
      <SettingsRow
        title={t("prompt")}
        description={t("app_prompt_description")}
        htmlFor="app-prompt"
      >
        <Textarea
          id="app-prompt"
          value={prompt.value}
          rows={6}
          onChange={(event) => prompt.setValue(event.target.value)}
          onBlur={() => prompt.commit()}
        />
      </SettingsRow>
    </SettingsGroup>
  );
}
