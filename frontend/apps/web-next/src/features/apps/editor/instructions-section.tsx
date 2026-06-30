"use client";

import { useTranslations } from "next-intl";
import { useState } from "react";
import { SettingsGroup, SettingsRow } from "@/components/composites/settings-rows";
import { Textarea } from "@/components/ui/textarea";
import { SaveRow } from "@/features/assistants/editor/general-section";
import type { App } from "../apps";
import { useUpdateApp } from "./use-app";

/**
 * App prompt. Prompt version history (PromptVersionDialog) is deferred, like
 * the assistant editor; tracked in the migration ledger.
 */
export function InstructionsSection({ app }: { app: App }) {
  const t = useTranslations();
  const update = useUpdateApp(app.id);

  const saved = app.prompt?.text ?? "";
  const [prompt, setPrompt] = useState(saved);
  const dirty = prompt !== saved;

  return (
    <SettingsGroup title={t("instructions")}>
      <SettingsRow
        title={t("prompt")}
        description={t("app_prompt_description")}
        htmlFor="app-prompt"
      >
        <Textarea
          id="app-prompt"
          value={prompt}
          rows={6}
          onChange={(event) => setPrompt(event.target.value)}
        />
        <SaveRow
          dirty={dirty}
          pending={update.isPending}
          onSave={() => update.mutate({ prompt: { text: prompt } })}
          onRevert={() => setPrompt(saved)}
        />
      </SettingsRow>
    </SettingsGroup>
  );
}
