"use client";

import { History } from "lucide-react";
import { useTranslations } from "next-intl";
import { useState } from "react";
import { SettingsGroup, SettingsRow } from "@/components/composites/settings-rows";
import { useAutosave, useAutosaveField } from "@/components/composites/use-autosave";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { PromptVersionDialog } from "@/features/prompts/prompt-version-dialog";
import type { App } from "../apps";
import { useUpdateApp } from "./use-app";

export function InstructionsSection({ app }: { app: App }) {
  const t = useTranslations();
  const update = useUpdateApp(app.id);
  const restorePrompt = useAutosave("app-prompt");
  const [showHistory, setShowHistory] = useState(false);

  const prompt = useAutosaveField({
    key: "app-prompt",
    value: app.prompt?.text ?? "",
    save: (value) => update.mutateAsync({ prompt: { text: value } }),
    commitDebounceMs: 1500,
    commitOnVisibilityChange: true
  });

  return (
    <SettingsGroup
      title={t("instructions")}
      headerEnd={
        <Button type="button" variant="ghost" size="sm" onClick={() => setShowHistory(true)}>
          <History className="size-4" /> {t("show_prompt_history")}
        </Button>
      }
    >
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
      <PromptVersionDialog
        resource={{ type: "app", id: app.id }}
        open={showHistory}
        onOpenChange={setShowHistory}
        onUseVersion={(text) => {
          prompt.setValue(text);
          void restorePrompt(() => update.mutateAsync({ prompt: { text } }));
        }}
      />
    </SettingsGroup>
  );
}
