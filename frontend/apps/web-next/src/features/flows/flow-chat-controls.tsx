"use client";

import { Button } from "@astryxdesign/core/Button";
import { useAnnounce } from "@astryxdesign/core/hooks";
import { useQueryClient } from "@tanstack/react-query";
import { MessageSquarePlus, Sparkles } from "lucide-react";
import { useTranslations } from "next-intl";
import { useState } from "react";
import { ModelSelector } from "@/components/ai-elements/model-selector";
import { ConfirmDialogControlled } from "@/components/composites/confirm-dialog";
import { useAppContext } from "@/components/providers/app-context";
import type { Schema } from "@/lib/api/models";
import { modelDisplayName } from "@/lib/models/model-display-name";
import {
  effectiveReasoningEffort,
  reasoningEffortLabel,
  reasoningEffortOptions
} from "@/features/chat/reasoning-effort";
import { ReasoningEffortSelector } from "@/features/chat/reasoning-selector";
import { useSpace } from "@/features/spaces/use-space";
import {
  flowKeys,
  startAuthoringConversation,
  updateAuthoringChat,
  type FlowAuthoringChat
} from "./flows-api";

type CompletionModel = Schema<"CompletionModelPublic">;
type Refused = (error: unknown, title: string) => void;

/** The compact (ghost) trigger look the chat composer's pickers share. */
const PICKER_CLASS =
  "text-ax-text-secondary hover:text-ax-text rounded-ax-element h-8 border-0 px-2 text-[13px] font-semibold pointer-coarse:h-11";

/**
 * The models the flow chat may use: the space's own (enabled there and
 * meeting its classification) that support tools. The core checks the
 * choice again.
 */
export function flowChatModels(models: readonly CompletionModel[]): CompletionModel[] {
  return models.filter((model) => model.supports_tool_calling && model.can_access !== false);
}

/** The model the chat answers with: the person's own while it is offered, else the default. */
export function flowChatModelId(
  chat: Pick<FlowAuthoringChat, "completion_model_id" | "default_completion_model_id">,
  models: readonly CompletionModel[]
): string | null {
  const own = chat.completion_model_id;
  if (own && models.some((model) => model.id === own)) return own;
  return chat.default_completion_model_id ?? null;
}

/**
 * Saves a change to the chat and puts the answer in the cache, so the panel
 * shows it (and a new conversation, should the core have started one). The
 * chat's assistant follows the change, so the composer reads it again.
 */
function useSaveChat(chat: FlowAuthoringChat) {
  const queryClient = useQueryClient();
  return async (save: () => Promise<FlowAuthoringChat>) => {
    const updated = await save();
    queryClient.setQueryData(flowKeys.authoringChat(chat.flow_id), updated);
    void queryClient.invalidateQueries({ queryKey: ["assistants", chat.assistant_id] });
    return updated;
  };
}

/**
 * The chat's model and reasoning effort, the same pickers the ordinary chat
 * has beside its composer. The list holds the space's models that support
 * tools; "Använd standard" follows the organisation's default for flow chats
 * (or the space's), which the list marks. A refused choice falls back and is
 * shown with the page's other refusals.
 */
export function FlowChatModelPickers({
  chat,
  onRefused
}: {
  chat: FlowAuthoringChat;
  onRefused: Refused;
}) {
  const t = useTranslations();
  const announce = useAnnounce();
  const { space } = useSpace();
  const { tenant } = useAppContext();
  const saveChat = useSaveChat(chat);
  const models = flowChatModels(space.completion_models);
  const effectiveId = flowChatModelId(chat, models);
  const effective = models.find((model) => model.id === effectiveId);
  const options = reasoningEffortOptions(effective);
  const nameOf = (id: string | null | undefined) => {
    const model = models.find((candidate) => candidate.id === id);
    return model ? modelDisplayName(model) : "";
  };

  async function change(
    body: Schema<"FlowAuthoringChatUpdateRequest">,
    done: (updated: FlowAuthoringChat) => string
  ) {
    try {
      const updated = await saveChat(() => updateAuthoringChat(chat, body));
      announce(done(updated));
    } catch (error) {
      onRefused(error, t("flows_chat_model_not_changed"));
      throw error;
    }
  }

  return (
    <span className="flex min-w-0 flex-wrap items-center gap-0.5">
      <ModelSelector
        models={models}
        selectedId={effectiveId}
        onSelect={(id) =>
          change({ completion_model_id: id }, () =>
            t("flows_chat_model_saved", { model: nameOf(id) })
          )
        }
        defaultChoice={{
          label: t("flows_chat_model_use_default"),
          modelId: chat.default_completion_model_id ?? null,
          isSelected: effectiveId === null || effectiveId !== chat.completion_model_id,
          onSelect: () =>
            change({ completion_model_id: null }, (updated) =>
              t("flows_chat_model_default_saved", {
                model: nameOf(updated.default_completion_model_id)
              })
            )
        }}
        size="sm"
        showPricing={tenant.show_model_pricing}
        className={PICKER_CLASS}
      />
      {options.length > 0 ? (
        <ReasoningEffortSelector
          options={options}
          stored={chat.reasoning_effort ?? null}
          policyDefault={null}
          defaultLabel={t("flows_chat_reasoning_model_default")}
          onSelect={(effort) =>
            change({ reasoning_effort: effort }, () => {
              const level = effectiveReasoningEffort({
                stored: effort,
                policyDefault: null,
                options
              });
              return t("flows_chat_reasoning_saved", {
                value: level
                  ? reasoningEffortLabel(level, t)
                  : t("flows_chat_reasoning_model_default")
              });
            })
          }
          className={PICKER_CLASS}
        />
      ) : null}
    </span>
  );
}

/**
 * "Ny konversation": after a confirmation the chat continues in a new, empty
 * conversation. The old one is kept for traceability but never answered or
 * shown again; the flow itself, its revisions and the audit log hold what
 * changed. The panel switches to the new conversation without a reload.
 */
export function NewConversationButton({
  chat,
  onRefused
}: {
  chat: FlowAuthoringChat;
  onRefused: Refused;
}) {
  const t = useTranslations();
  const announce = useAnnounce();
  const saveChat = useSaveChat(chat);
  const [open, setOpen] = useState(false);
  const [pending, setPending] = useState(false);

  async function start() {
    if (pending) return;
    setPending(true);
    try {
      await saveChat(() => startAuthoringConversation(chat));
      setOpen(false);
      announce(t("flows_chat_new_conversation_started"));
    } catch (error) {
      setOpen(false);
      onRefused(error, t("flows_chat_new_conversation_failed"));
    } finally {
      setPending(false);
    }
  }

  return (
    <>
      <Button
        label={t("flows_chat_new_conversation")}
        variant="ghost"
        size="sm"
        icon={<MessageSquarePlus aria-hidden className="size-4" />}
        onClick={() => setOpen(true)}
      />
      <ConfirmDialogControlled
        open={open}
        onOpenChange={setOpen}
        title={t("flows_chat_new_conversation_title")}
        description={t("flows_chat_new_conversation_description")}
        confirmLabel={t("flows_chat_new_conversation_confirm")}
        variant="default"
        pending={pending}
        onConfirm={() => void start()}
      />
    </>
  );
}

/**
 * "Optimera flödet": puts a prepared request in the composer that asks the
 * chat to review the flow with its suggestions tool and propose
 * improvements. The person reads it, edits it if they like, and sends it;
 * nothing is sent from here.
 */
export function OptimizeFlowButton({ onAskChat }: { onAskChat: (text: string) => void }) {
  const t = useTranslations();
  return (
    <Button
      label={t("flow_suggestions_optimize")}
      variant="ghost"
      size="sm"
      icon={<Sparkles aria-hidden className="size-4" />}
      onClick={() => onAskChat(t("flow_suggestions_optimize_request"))}
    />
  );
}
