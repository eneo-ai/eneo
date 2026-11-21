import { FileText, History, Maximize2, Sparkles } from "lucide-react";
import { useFormatter, useTranslations } from "use-intl";
import { useState } from "react";
import { AssistantContextMeter } from "./assistant-context-meter";
import type { Schema } from "@/lib/api/models";
import { assistantToolModel } from "./effective-config";
import {
  MARKED_ROW_CLASS,
  SettingsGroup,
  SettingsMarkLabel,
  useSettingsMark
} from "@/components/composites/settings-rows";
import { useAutosaveField } from "@/components/composites/use-autosave";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle
} from "@/components/ui/dialog";
import { Textarea } from "@/components/ui/textarea";
import { formatDateTime } from "@/lib/format";
import { cn } from "@/lib/utils";
import { PromptVersionDialog } from "@/features/prompts/prompt-version-dialog";
import { promptDraftsMatch, type PromptDraft } from "@/features/prompts/prompt-draft";
import { useSpace } from "@/features/spaces/use-space";
import { isPromptLocked } from "./effective-config";
import { useUpdateAssistant, type Assistant } from "./use-assistant";

const PROMPT_AUTOSAVE_DEBOUNCE_MS = 1500;

/** Right-aligned muted line: character count + a markdown hint. */
function PromptMeta({ text }: { text: string }) {
  const t = useTranslations();
  const format = useFormatter();
  const characters = format.number(text.length);

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

/** The prompt. Saving creates a new prompt version backend-side. */
export function InstructionsSection({
  assistant,
  contextModel,
  modelConfirmed = true,
  onAskPrompt
}: {
  assistant: Assistant;
  contextModel?: Pick<Schema<"CompletionModelPublic">, "id" | "token_limit"> | null;
  modelConfirmed?: boolean;
  /**
   * "Hjälp mig skriva instruktionerna" beside the prompt: opens the helper
   * with a request about it in the composer. Absent, it is not offered (no
   * helper, or a prompt the person may not change here).
   */
  onAskPrompt?: () => void;
}) {
  const t = useTranslations();
  const { space } = useSpace();
  const update = useUpdateAssistant(assistant.id);
  const savedPrompt = assistant.prompt?.text ?? "";
  const promptLocked = isPromptLocked(assistant.effective_config);
  const savedDescription = assistant.prompt?.description ?? "";
  const [showHistory, setShowHistory] = useState(false);
  const [expanded, setExpanded] = useState(false);

  // Each save creates a new prompt version, so commit on blur, after a pause,
  // or on an explicit apply rather than on every keystroke.
  const promptField = useAutosaveField<PromptDraft>({
    key: "assistant-prompt",
    value: { kind: "server", text: savedPrompt, description: savedDescription },
    equals: promptDraftsMatch,
    validate: () => !promptLocked,
    save: (value) =>
      update.mutateAsync({
        prompt: { text: value.text, description: value.kind === "manual" ? "" : value.description }
      }),
    commitDebounceMs: PROMPT_AUTOSAVE_DEBOUNCE_MS,
    commitOnVisibilityChange: true
  });
  const prompt = promptField.value.text;

  function editPrompt(text: string) {
    promptField.setValue({ kind: "manual", text });
  }

  const effectiveModelId = assistantToolModel(space.completion_models, assistant)?.id;
  const model =
    contextModel === undefined
      ? (space.completion_models.find((candidate) => candidate.id === effectiveModelId) ?? null)
      : contextModel;

  const promptMark = useSettingsMark("assistant-prompt");
  const promptLabel = (
    <label htmlFor="assistant-prompt" className="text-sm font-medium">
      {t("prompt")}
    </label>
  );

  return (
    <SettingsGroup title={t("instructions")}>
      <div className={cn("flex flex-col gap-2", promptMark && MARKED_ROW_CLASS)}>
        {/* The buttons move under the label where both do not fit on a line. */}
        <div className="flex flex-wrap items-start justify-between gap-x-3 gap-y-1">
          <div className="flex min-w-0 flex-1 basis-56 flex-col gap-0.5">
            {promptMark ? (
              <span className="flex flex-wrap items-center gap-x-2 gap-y-1">
                {promptLabel}
                <SettingsMarkLabel label={promptMark} />
              </span>
            ) : (
              promptLabel
            )}
            <p className="text-muted-foreground text-sm">{t("describe_assistant_behavior")}</p>
          </div>
          {/* Wrapped under the label on a phone: the ghost buttons' own inset is pulled
              back so their icons start on the gutter with the label. */}
          <div className="phone:-ms-2.5 flex min-w-0 flex-wrap items-center gap-1">
            {onAskPrompt && !promptLocked && (
              <Button type="button" variant="ghost" size="sm" onClick={onAskPrompt}>
                <Sparkles className="size-4" /> {t("helper_ask_prompt")}
              </Button>
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
          onChange={(event) => editPrompt(event.target.value)}
          onBlur={() => void promptField.commit()}
        />

        <div className="flex flex-wrap items-center justify-between gap-2">
          <AssistantContextMeter
            assistantId={assistant.id}
            prompt={promptLocked ? undefined : prompt}
            attachments={assistant.attachments ?? []}
            model={model}
            modelConfirmed={modelConfirmed}
            revision={assistant.updated_at}
          />
          <PromptMeta text={prompt} />
        </div>
      </div>

      <PromptVersionDialog
        resource={{ type: "assistant", id: assistant.id }}
        open={showHistory && !promptLocked}
        onOpenChange={setShowHistory}
        onUseVersion={(version) => {
          if (promptLocked) return;
          const value: PromptDraft = {
            kind: "annotated",
            text: version.text,
            description: t("prompt_restored_from_date", {
              date: version.created_at ? formatDateTime(version.created_at) : t("unknown")
            })
          };
          promptField.setValue(value);
          void promptField.commit(value);
        }}
      />
      <Dialog open={expanded} onOpenChange={setExpanded}>
        <DialogContent className="flex h-[min(760px,calc(100dvh-2rem))] max-w-[calc(100%-2rem)] flex-col gap-5 p-5 sm:max-w-5xl sm:p-6">
          <DialogHeader>
            <DialogTitle>{t("prompt")}</DialogTitle>
            <DialogDescription>{t("describe_assistant_behavior")}</DialogDescription>
          </DialogHeader>
          <Textarea
            aria-label={t("prompt")}
            value={prompt}
            disabled={promptLocked}
            className="min-h-0 flex-1 resize-none text-base leading-6"
            onChange={(event) => editPrompt(event.target.value)}
            onBlur={() => void promptField.commit()}
          />
          <div className="flex justify-end">
            <PromptMeta text={prompt} />
          </div>
        </DialogContent>
      </Dialog>
    </SettingsGroup>
  );
}
