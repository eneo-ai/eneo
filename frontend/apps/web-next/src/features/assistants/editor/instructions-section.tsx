"use client";

import { FileText, History, Maximize2 } from "lucide-react";
import { useTranslations } from "next-intl";
import { useMemo, useState } from "react";
import { SettingsGroup, SettingsRow } from "@/components/composites/settings-rows";
import { useReportDirty } from "@/components/composites/save-status";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle
} from "@/components/ui/dialog";
import { Textarea } from "@/components/ui/textarea";
import { SaveRow } from "./general-section";
import { PromptVersionDialog } from "./prompt-version-dialog";
import { useUpdateAssistant, type Assistant } from "./use-assistant";

// Rough heuristic: ~4 characters per token. Good enough for a live editor hint.
const CHARS_PER_TOKEN = 4;

/** Right-aligned muted line: character count, estimated tokens, and a markdown hint. */
function PromptMeta({ text }: { text: string }) {
  const t = useTranslations();
  const numberFormat = useMemo(() => new Intl.NumberFormat(undefined), []);
  const characters = numberFormat.format(Math.round(text.length));
  const tokens = numberFormat.format(Math.ceil(text.length / CHARS_PER_TOKEN));

  return (
    <div className="text-muted-foreground flex flex-wrap items-center justify-end gap-x-3 gap-y-1 text-xs">
      <span className="inline-flex items-center gap-1">
        <FileText aria-hidden="true" className="size-3.5" />
        {t("markdown_supported")}
      </span>
      <span>
        {characters} {t("characters")} · ~{tokens} {t("tokens")}
      </span>
    </div>
  );
}

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
  const [expanded, setExpanded] = useState(false);

  const dirty = prompt !== savedPrompt;
  useReportDirty("instructions", dirty);

  return (
    <SettingsGroup title={t("instructions")}>
      <SettingsRow
        title={t("prompt")}
        description={t("describe_assistant_behavior")}
        htmlFor="assistant-prompt"
      >
        <div className="flex justify-end gap-1">
          <Button type="button" variant="ghost" size="sm" onClick={() => setShowHistory(true)}>
            <History className="size-4" /> {t("show_prompt_history")}
          </Button>
          <Button
            type="button"
            variant="ghost"
            size="icon"
            aria-label={t("expand")}
            onClick={() => setExpanded(true)}
          >
            <Maximize2 className="size-4" />
          </Button>
        </div>
        <Textarea
          id="assistant-prompt"
          value={prompt}
          rows={8}
          className="min-h-32 text-base"
          onChange={(event) => setPrompt(event.target.value)}
        />
        <PromptMeta text={prompt} />
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
        <Dialog open={expanded} onOpenChange={setExpanded}>
          <DialogContent className="flex h-[82vh] max-h-[760px] max-w-[calc(100%-2rem)] flex-col gap-5 p-5 sm:min-h-[560px] sm:max-w-5xl sm:p-6">
            <DialogHeader>
              <DialogTitle>{t("prompt")}</DialogTitle>
              <DialogDescription>{t("describe_assistant_behavior")}</DialogDescription>
            </DialogHeader>
            <Textarea
              aria-label={t("prompt")}
              value={prompt}
              className="min-h-0 flex-1 resize-none text-base leading-6"
              onChange={(event) => setPrompt(event.target.value)}
            />
            <PromptMeta text={prompt} />
          </DialogContent>
        </Dialog>
      </SettingsRow>
    </SettingsGroup>
  );
}
