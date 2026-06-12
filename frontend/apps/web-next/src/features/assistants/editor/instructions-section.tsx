"use client";

import { useTranslations } from "next-intl";
import { useState } from "react";
import { SettingsGroup, SettingsRow } from "@/components/composites/settings-rows";
import { Textarea } from "@/components/ui/textarea";
import { SaveRow } from "./general-section";
import { useUpdateAssistant, type Assistant } from "./use-assistant";

/**
 * The prompt. Prompt version history and the prompt-guide helper are deferred
 * (tracked in the migration ledger); saving creates a new prompt version
 * backend-side either way.
 */
export function InstructionsSection({ assistant }: { assistant: Assistant }) {
  const t = useTranslations();
  const update = useUpdateAssistant(assistant.id);
  const savedPrompt = assistant.prompt?.text ?? "";
  const [prompt, setPrompt] = useState(savedPrompt);

  const dirty = prompt !== savedPrompt;

  return (
    <SettingsGroup title={t("instructions")}>
      <SettingsRow title={t("prompt")} description={t("describe_assistant_behavior")}>
        <Textarea
          value={prompt}
          rows={8}
          className="min-h-32 text-base"
          onChange={(event) => setPrompt(event.target.value)}
        />
        <SaveRow
          dirty={dirty}
          pending={update.isPending}
          onSave={() => update.mutate({ prompt: { text: prompt, description: "" } })}
          onRevert={() => setPrompt(savedPrompt)}
        />
      </SettingsRow>
    </SettingsGroup>
  );
}
