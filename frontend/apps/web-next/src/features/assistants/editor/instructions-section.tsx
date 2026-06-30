"use client";

import { History } from "lucide-react";
import { useTranslations } from "next-intl";
import { useState } from "react";
import { SettingsGroup, SettingsRow } from "@/components/composites/settings-rows";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { SaveRow } from "./general-section";
import { PromptVersionDialog } from "./prompt-version-dialog";
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
  const [showHistory, setShowHistory] = useState(false);

  const dirty = prompt !== savedPrompt;

  return (
    <SettingsGroup title={t("instructions")}>
      <SettingsRow
        title={t("prompt")}
        description={t("describe_assistant_behavior")}
        htmlFor="assistant-prompt"
      >
        <div className="flex justify-end">
          <Button type="button" variant="ghost" size="sm" onClick={() => setShowHistory(true)}>
            <History className="size-4" /> {t("show_prompt_history")}
          </Button>
        </div>
        <Textarea
          id="assistant-prompt"
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
        <PromptVersionDialog
          assistantId={assistant.id}
          open={showHistory}
          onOpenChange={setShowHistory}
          onUseVersion={(text) => setPrompt(text)}
        />
      </SettingsRow>
    </SettingsGroup>
  );
}
