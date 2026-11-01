"use client";

import { History } from "lucide-react";
import { useTranslations } from "use-intl";
import { useState } from "react";
import { SettingsGroup, SettingsRow } from "@/components/composites/settings-rows";
import { useAutosaveField } from "@/components/composites/use-autosave";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { formatDateTime } from "@/lib/format";
import { PromptVersionDialog } from "@/features/prompts/prompt-version-dialog";
import { promptDraftsMatch, type PromptDraft } from "@/features/prompts/prompt-draft";
import type { App } from "../apps";
import { useUpdateApp } from "./use-app";

export function InstructionsSection({ app }: { app: App }) {
  const t = useTranslations();
  const update = useUpdateApp(app.id);
  const [showHistory, setShowHistory] = useState(false);

  const savedText = app.prompt?.text ?? "";
  const savedDescription = app.prompt?.description ?? "";
  const prompt = useAutosaveField<PromptDraft>({
    key: "app-prompt",
    value: { kind: "server", text: savedText, description: savedDescription },
    equals: promptDraftsMatch,
    save: (value) =>
      update.mutateAsync({
        prompt: {
          text: value.text,
          ...(value.kind === "manual" ? {} : { description: value.description })
        }
      }),
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
          value={prompt.value.text}
          rows={6}
          onChange={(event) => {
            const text = event.target.value;
            prompt.setValue({ kind: "manual", text });
          }}
          onBlur={() => prompt.commit()}
        />
      </SettingsRow>
      <PromptVersionDialog
        resource={{ type: "app", id: app.id }}
        open={showHistory}
        onOpenChange={setShowHistory}
        onUseVersion={(version) => {
          const value: PromptDraft = {
            kind: "annotated",
            text: version.text,
            description: t("prompt_restored_from_date", {
              date: version.created_at ? formatDateTime(version.created_at) : t("unknown")
            })
          };
          prompt.setValue(value);
          void prompt.commit(value);
        }}
      />
    </SettingsGroup>
  );
}
