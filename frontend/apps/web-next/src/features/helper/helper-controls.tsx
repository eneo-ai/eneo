import { useAnnounce } from "@astryxdesign/core/hooks";
import { IconButton } from "@astryxdesign/core/IconButton";
import { Popover } from "@astryxdesign/core/Popover";
import { Text } from "@astryxdesign/core/Text";
import { useQueryClient } from "@tanstack/react-query";
import { MessageSquarePlus, SlidersHorizontal } from "lucide-react";
import { useTranslations } from "use-intl";
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
import type { HelperAdapter, HelperChat, HelperChatApi, HelperChatUpdate } from "./helper-adapter";

type CompletionModel = Schema<"CompletionModelPublic">;
type Refused = HelperAdapter["onRefused"];

/**
 * The models the helper chat may use: the space's own (enabled there and
 * meeting its classification) that support tools. The core checks the
 * choice again.
 */
export function helperChatModels(models: readonly CompletionModel[]): CompletionModel[] {
  return models.filter((model) => model.supports_tool_calling && model.can_access !== false);
}

/** The model the chat answers with: the person's own while it is offered, else the default. */
export function helperChatModelId(
  chat: Pick<HelperChat, "completion_model_id" | "default_completion_model_id">,
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
function useSaveChat(chat: HelperChat, api: HelperChatApi) {
  const queryClient = useQueryClient();
  return async (save: () => Promise<HelperChat>) => {
    const updated = await save();
    // A read of the chat still on its way began before this change: it must not land after it.
    await queryClient.cancelQueries({ queryKey: api.key });
    queryClient.setQueryData(api.key, updated);
    void queryClient.invalidateQueries({ queryKey: ["assistants", chat.assistant_id] });
    return updated;
  };
}

/**
 * The chat's settings behind one button in the panel's title row, since the
 * panel is narrow: a popover with the model and reasoning-effort pickers the
 * ordinary chat has beside its composer, here as labelled fields. The model
 * list holds the space's models that support tools; "Använd standard"
 * follows the organisation's default for helper chats (or the space's),
 * which the list marks. A refused choice falls back and is shown with the
 * page's other refusals.
 */
export function HelperChatSettings({
  chat,
  api,
  onRefused
}: {
  chat: HelperChat;
  api: HelperChatApi;
  onRefused: Refused;
}) {
  const t = useTranslations();
  const [open, setOpen] = useState(false);
  return (
    <Popover
      isOpen={open}
      onOpenChange={setOpen}
      placement="below"
      alignment="end"
      width={320}
      label={t("flows_chat_settings")}
      closeButtonLabel={t("close")}
      content={<HelperChatSettingsFields chat={chat} api={api} onRefused={onRefused} />}
    >
      <IconButton
        label={t("flows_chat_settings")}
        tooltip={t("flows_chat_settings")}
        icon={<SlidersHorizontal aria-hidden className="size-4" />}
        variant="ghost"
        size="sm"
      />
    </Popover>
  );
}

function HelperChatSettingsFields({
  chat,
  api,
  onRefused
}: {
  chat: HelperChat;
  api: HelperChatApi;
  onRefused: Refused;
}) {
  const t = useTranslations();
  const announce = useAnnounce();
  const { space } = useSpace();
  const { tenant } = useAppContext();
  const saveChat = useSaveChat(chat, api);
  const models = helperChatModels(space.completion_models);
  const effectiveId = helperChatModelId(chat, models);
  const effective = models.find((model) => model.id === effectiveId);
  const options = reasoningEffortOptions(effective);
  const nameOf = (id: string | null | undefined) => {
    const model = models.find((candidate) => candidate.id === id);
    return model ? modelDisplayName(model) : "";
  };

  async function change(body: HelperChatUpdate, done: (updated: HelperChat) => string) {
    try {
      const updated = await saveChat(() => api.update(chat.session_id, body));
      announce(done(updated));
    } catch (error) {
      onRefused(error, t("flows_chat_model_not_changed"));
      throw error;
    }
  }

  return (
    <div className="flex min-w-0 flex-col gap-3">
      <Text type="supporting" size="sm" as="p" display="block" className="m-0">
        {t("flows_chat_settings_hint")}
      </Text>
      <ModelSelector
        models={models}
        selectedId={effectiveId}
        field={{ label: t("completion_model") }}
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
        showPricing={tenant.show_model_pricing}
      />
      {options.length > 0 ? (
        <ReasoningEffortSelector
          options={options}
          stored={chat.reasoning_effort ?? null}
          policyDefault={null}
          defaultLabel={t("flows_chat_reasoning_model_default")}
          appearance="field"
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
        />
      ) : null}
    </div>
  );
}

/**
 * "Ny konversation": after a confirmation the chat continues in a new, empty
 * conversation. The old one is kept for traceability but never answered or
 * shown again; `description` says what the target keeps. The panel switches
 * to the new conversation without a reload.
 */
export function NewConversationButton({
  chat,
  api,
  description,
  onRefused
}: {
  chat: HelperChat;
  api: HelperChatApi;
  description: string;
  onRefused: Refused;
}) {
  const t = useTranslations();
  const announce = useAnnounce();
  const saveChat = useSaveChat(chat, api);
  const [open, setOpen] = useState(false);
  const [pending, setPending] = useState(false);

  async function start() {
    if (pending) return;
    setPending(true);
    try {
      await saveChat(() => api.startConversation(chat.session_id));
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
      <IconButton
        label={t("flows_chat_new_conversation")}
        tooltip={t("flows_chat_new_conversation")}
        variant="ghost"
        size="sm"
        icon={<MessageSquarePlus aria-hidden className="size-4" />}
        onClick={() => setOpen(true)}
      />
      <ConfirmDialogControlled
        open={open}
        onOpenChange={setOpen}
        title={t("flows_chat_new_conversation_title")}
        description={description}
        confirmLabel={t("flows_chat_new_conversation_confirm")}
        variant="default"
        pending={pending}
        onConfirm={() => void start()}
      />
    </>
  );
}
