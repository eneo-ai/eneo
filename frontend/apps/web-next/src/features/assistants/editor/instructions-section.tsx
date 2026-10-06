"use client";

import { useQuery } from "@tanstack/react-query";
import { FileText, History, Maximize2, Sparkles } from "lucide-react";
import { useTranslations } from "next-intl";
import { useCallback, useEffect, useRef, useState } from "react";
import { ContextBudget, type ContextSegment } from "@/components/composites/context-budget";
import { SettingsGroup } from "@/components/composites/settings-rows";
import { useAutosave, useDirtySaveStatus } from "@/components/composites/use-autosave";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle
} from "@/components/ui/dialog";
import { Textarea } from "@/components/ui/textarea";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { browserApi } from "@/lib/api/browser";
import { formatDateTime } from "@/lib/format";
import {
  promptGuideAvailabilityQueryOptions,
  type HelperAvailability
} from "@/features/help-assistants/prompt-guide/helper-runs";
import { PromptGuideDialog } from "@/features/help-assistants/prompt-guide/prompt-guide-dialog";
import { PromptVersionDialog } from "@/features/prompts/prompt-version-dialog";
import { useSpace } from "@/features/spaces/use-space";
import { isPromptLocked } from "./effective-config";
import { useUpdateAssistant, type Assistant } from "./use-assistant";

// Rough heuristic: ~4 characters per token. Good enough for a live editor hint.
const CHARS_PER_TOKEN = 4;
const PROMPT_AUTOSAVE_DEBOUNCE_MS = 1500;

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
 * The prompt. Saving creates a new prompt version backend-side; Prompt Guide
 * only mutates local editor state and relies on this same save path.
 */
export function InstructionsSection({
  assistant,
  promptGuide = true
}: {
  assistant: Assistant;
  promptGuide?: boolean;
}) {
  const t = useTranslations();
  const { space } = useSpace();
  const update = useUpdateAssistant(assistant.id);
  const autosave = useAutosave("assistant-prompt");
  const savedPrompt = assistant.prompt?.text ?? "";
  const promptLocked = isPromptLocked(assistant.effective_config);
  const [prompt, setPrompt] = useState(savedPrompt);
  const [promptDescription, setPromptDescription] = useState("");
  const [showHistory, setShowHistory] = useState(false);
  const [showPromptGuide, setShowPromptGuide] = useState(false);
  const [expanded, setExpanded] = useState(false);
  const promptGuideAvailability = useQuery({
    ...promptGuideAvailabilityQueryOptions(browserApi, assistant.id),
    enabled: promptGuide
  });

  const dirty = prompt !== savedPrompt;
  useDirtySaveStatus("assistant-prompt", dirty);

  // Adopt the saved prompt when it changes server-side (our save landing, or a
  // version restored elsewhere) unless the user has unsaved local edits.
  const serverRef = useRef(savedPrompt);
  useEffect(() => {
    if (serverRef.current === savedPrompt) return;
    const previous = serverRef.current;
    serverRef.current = savedPrompt;
    setPrompt((current) => (current === previous ? savedPrompt : current));
  }, [savedPrompt]);

  // Each save creates a new prompt version, so commit on blur or an explicit
  // apply rather than on every keystroke.
  const commit = useCallback(
    async (text = prompt, description = promptDescription) => {
      if (promptLocked) return;
      if (text === savedPrompt) return;
      const result = await autosave(() => update.mutateAsync({ prompt: { text, description } }));
      if (result !== undefined) setPromptDescription("");
    },
    [autosave, prompt, promptDescription, promptLocked, savedPrompt, update]
  );

  useEffect(() => {
    if (!dirty) return;
    const timer = window.setTimeout(() => void commit(), PROMPT_AUTOSAVE_DEBOUNCE_MS);
    return () => window.clearTimeout(timer);
  }, [commit, dirty]);

  useEffect(() => {
    if (!dirty) return;
    const handler = () => {
      if (document.visibilityState === "hidden") void commit();
    };
    document.addEventListener("visibilitychange", handler);
    return () => document.removeEventListener("visibilitychange", handler);
  }, [commit, dirty]);

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

  function promptGuideDisabledTooltip(
    reason: HelperAvailability["disabled_reason"] | null | undefined
  ): string {
    switch (reason) {
      case "role_disabled":
        return t("prompt_guide_disabled_role_disabled");
      case "role_not_visible":
        return t("prompt_guide_disabled_role_not_visible");
      case "no_completion_model":
        return t("prompt_guide_disabled_no_completion_model");
      case "no_edit_rights":
        return t("prompt_guide_disabled_no_edit_rights");
      case "no_assignment":
      default:
        return t("prompt_guide_disabled_no_assignment");
    }
  }

  const availability = promptGuideAvailability.data;

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
            {promptGuide && availability && !promptLocked && (
              <Tooltip>
                <TooltipTrigger asChild>
                  <span className="inline-flex">
                    <Button
                      type="button"
                      variant="ghost"
                      size="sm"
                      disabled={!availability.available}
                      onClick={() => setShowPromptGuide(true)}
                    >
                      <Sparkles className="size-4" /> {t("prompt_guide_button")}
                    </Button>
                  </span>
                </TooltipTrigger>
                <TooltipContent>
                  {availability.available
                    ? t("prompt_guide_button_tooltip")
                    : promptGuideDisabledTooltip(availability.disabled_reason)}
                </TooltipContent>
              </Tooltip>
            )}
            {!promptLocked && (
              <Button type="button" variant="ghost" size="sm" onClick={() => setShowHistory(true)}>
                <History className="size-4" /> {t("show_prompt_history")}
              </Button>
            )}
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

        {promptLocked && (
          <p className="border-warning/30 bg-warning/10 text-warning rounded-md border px-3 py-2 text-sm">
            <span className="font-semibold">{t("warning")}:</span>{" "}
            {t("governance_assistant_prompt_locked_hint")}
          </p>
        )}

        <Textarea
          id="assistant-prompt"
          value={prompt}
          disabled={promptLocked}
          rows={12}
          className="min-h-72 w-full resize-y text-base leading-6"
          onChange={(event) => {
            setPrompt(event.target.value);
            setPromptDescription("");
          }}
          onBlur={() => void commit()}
        />

        <div className="flex flex-wrap items-center justify-between gap-2">
          <ContextBudget segments={budgetSegments} maxTokens={model?.token_limit ?? null} />
          <PromptMeta text={prompt} />
        </div>
      </div>

      <PromptGuideDialog
        open={showPromptGuide && !promptLocked}
        onOpenChange={setShowPromptGuide}
        targetId={assistant.id}
        targetPrompt={prompt}
        hasUnsavedPromptChanges={dirty}
        onApply={(text) => {
          if (promptLocked) return;
          const description = t("prompt_guide_apply_description", {
            date: formatDateTime(new Date().toISOString())
          });
          setPrompt(text);
          setPromptDescription(description);
          void commit(text, description);
        }}
      />
      <PromptVersionDialog
        resource={{ type: "assistant", id: assistant.id }}
        open={showHistory && !promptLocked}
        onOpenChange={setShowHistory}
        onUseVersion={(text) => {
          if (promptLocked) return;
          setPrompt(text);
          setPromptDescription("");
          void commit(text, "");
        }}
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
            disabled={promptLocked}
            className="min-h-0 flex-1 resize-none text-base leading-6"
            onChange={(event) => {
              setPrompt(event.target.value);
              setPromptDescription("");
            }}
            onBlur={() => void commit()}
          />
          <div className="flex justify-end">
            <PromptMeta text={prompt} />
          </div>
        </DialogContent>
      </Dialog>
    </SettingsGroup>
  );
}
