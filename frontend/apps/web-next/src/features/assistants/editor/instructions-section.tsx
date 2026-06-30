"use client";

import { FileText, History, Maximize2 } from "lucide-react";
import { useTranslations } from "next-intl";
import { useState } from "react";
import { ContextBudget, type ContextSegment } from "@/components/composites/context-budget";
import { SettingsGroup } from "@/components/composites/settings-rows";
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
import { useSpace } from "@/features/spaces/use-space";
import { SaveRow } from "./general-section";
import { PromptVersionDialog } from "./prompt-version-dialog";
import { useUpdateAssistant, type Assistant } from "./use-assistant";

// Rough heuristic: ~4 characters per token. Good enough for a live editor hint.
const CHARS_PER_TOKEN = 4;

/** Right-aligned muted line: character count + a markdown hint. */
function PromptMeta({ text }: { text: string }) {
  const t = useTranslations();
  const characters = new Intl.NumberFormat(undefined).format(Math.round(text.length));

  return (
    <span className="text-muted-foreground inline-flex items-center gap-3 text-xs">
      <span>
        {characters} {t("characters")}
      </span>
      <span className="inline-flex items-center gap-1">
        <FileText aria-hidden="true" className="size-3.5" />
        {t("markdown_supported")}
      </span>
    </span>
  );
}

/**
 * The prompt. Prompt version history and the prompt-guide helper are deferred
 * (tracked in the migration ledger); saving creates a new prompt version
 * backend-side either way.
 */
export function InstructionsSection({ assistant }: { assistant: Assistant }) {
  const t = useTranslations();
  const { space } = useSpace();
  const update = useUpdateAssistant(assistant.id);
  const savedPrompt = assistant.prompt?.text ?? "";
  const [prompt, setPrompt] = useState(savedPrompt);
  const [showHistory, setShowHistory] = useState(false);
  const [expanded, setExpanded] = useState(false);

  const dirty = prompt !== savedPrompt;
  useReportDirty("instructions", dirty);

  const promptTokens = Math.ceil(prompt.length / CHARS_PER_TOKEN);
  const attachmentTokens = (assistant.attachments ?? []).reduce(
    (sum, file) => sum + (file.token_count ?? 0),
    0
  );
  const model =
    space.completion_models.find((candidate) => candidate.id === assistant.completion_model?.id) ??
    null;
  const budgetSegments: ContextSegment[] = [
    { key: "prompt", label: t("prompt"), tokens: promptTokens, className: "bg-chart-1" },
    {
      key: "attachments",
      label: t("attachments"),
      tokens: attachmentTokens,
      className: "bg-chart-2"
    }
  ];

  return (
    <SettingsGroup title={t("instructions")}>
      <div className="flex flex-col gap-2">
        <div className="flex items-start justify-between gap-3">
          <div className="flex flex-col gap-0.5">
            <label htmlFor="assistant-prompt" className="text-sm font-medium">
              {t("prompt")}
            </label>
            <p className="text-muted-foreground text-sm">{t("describe_assistant_behavior")}</p>
          </div>
          <div className="flex shrink-0 items-center gap-1">
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
        </div>

        <Textarea
          id="assistant-prompt"
          value={prompt}
          rows={12}
          className="min-h-72 w-full resize-y text-base leading-6"
          onChange={(event) => setPrompt(event.target.value)}
        />

        <div className="flex flex-wrap items-center justify-between gap-2">
          <ContextBudget segments={budgetSegments} maxTokens={model?.token_limit ?? null} />
          <PromptMeta text={prompt} />
        </div>

        <SaveRow
          dirty={dirty}
          pending={update.isPending}
          onSave={() => update.mutate({ prompt: { text: prompt, description: "" } })}
          onRevert={() => setPrompt(savedPrompt)}
        />
      </div>

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
          <div className="flex justify-end">
            <PromptMeta text={prompt} />
          </div>
        </DialogContent>
      </Dialog>
    </SettingsGroup>
  );
}
