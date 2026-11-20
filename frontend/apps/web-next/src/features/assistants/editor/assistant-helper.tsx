import { Button } from "@astryxdesign/core/Button";
import { ToggleButton } from "@astryxdesign/core/ToggleButton";
import { useQueryClient } from "@tanstack/react-query";
import { MessageSquarePlus, Sparkles } from "lucide-react";
import { useTranslations } from "use-intl";
import type { ReactNode, Ref } from "react";
import { EneoApiError } from "@/lib/api/errors";
import { toastApiError } from "@/lib/api/toast";
import { invalidateExpiringApiKeys } from "@/features/api-keys/api-keys";
import type { ChatReferences } from "@/features/chat/chat-references";
import type { HelperAdapter } from "@/features/helper/helper-adapter";
import { useSpace } from "@/features/spaces/use-space";
import { assistantHelperApi, type AssistantHelperAvailability } from "./assistant-helper-api";
import { changeOf, isAssistantToolCall } from "./assistant-helper-changes";
import { assistantHelperCardFor } from "./assistant-helper-cards";
import { changedFields } from "./assistant-helper-form";
import type { Assistant } from "./use-assistant";

type UnavailableReason = NonNullable<AssistantHelperAvailability["reason"]>;

/** Why the helper is not open to the person, by the availability's reason. */
const UNAVAILABLE_KEYS: Record<UnavailableReason, string> = {
  no_model: "helper_unavailable_no_model",
  no_edit_rights: "helper_no_access",
  not_supported: "helper_unavailable_not_supported",
  disabled: "helper_unavailable_disabled",
  no_permission: "helper_unavailable_no_permission"
};

/** The assistant's helper chat's refusals (the error's `code`), in plain words. */
const REFUSAL_KEYS: Record<string, string> = {
  helper_chat_no_model: "helper_unavailable_no_model",
  helper_chat_no_edit_rights: "helper_no_access",
  helper_chat_not_supported: "helper_unavailable_not_supported",
  helper_chat_disabled: "helper_unavailable_disabled",
  helper_chat_no_permission: "helper_unavailable_no_permission",
  helper_chat_model_without_tools: "helper_refusal_model_without_tools",
  helper_chat_model_below_classification: "helper_refusal_model_below_classification",
  helper_chat_model_not_in_space: "helper_refusal_model_not_in_space",
  helper_chat_reasoning_effort_unsupported: "helper_refusal_reasoning_effort_unsupported"
};

/**
 * The helper panel's adapter for an assistant in its settings editor. The
 * chat is open to the person as the availability read says (it is asked for
 * only then); an assistant has no lock and no revision. The chat has one
 * mode: every change it wants shows as a proposal card that the person
 * applies, and a publish or unpublish waits for the person's approval. A
 * conversation's history can hold a direct change by the helper, whose card
 * has an undo. When one of the chat's tools finishes, and when an answer
 * ends, the assistant and its space are read again, so the form shows what
 * changed (a publish also the API keys' expiry notices, as the publishing
 * section's own publish does), and a publish is handed to `onChanged`. The
 * page hands it what the chat can refer to (the assistant's settings), the
 * composer's "@" button and what runs before a message goes.
 */
export function useAssistantHelper({
  assistant,
  availability,
  references,
  footerActions,
  onChanged,
  beforeSend
}: {
  assistant: Assistant;
  /** The availability read; undefined while it is pending or failed. */
  availability: AssistantHelperAvailability | undefined;
  references?: ChatReferences;
  footerActions?: ReactNode;
  /** The settings a `publish_assistant` call of this visit actually changed. */
  onChanged?: (fields: string[]) => void;
  beforeSend?: HelperAdapter["beforeSend"];
}): HelperAdapter {
  const t = useTranslations();
  const queryClient = useQueryClient();
  const { routeId } = useSpace();
  const refusalText = (reason: string | undefined) => {
    const key = reason ? REFUSAL_KEYS[reason] : undefined;
    return key ? t(key) : null;
  };
  const refresh = () => {
    void queryClient.invalidateQueries({ queryKey: ["assistants", assistant.id] });
    void queryClient.invalidateQueries({ queryKey: ["spaces", routeId] });
  };
  return {
    api: assistantHelperApi(assistant.id),
    unavailable:
      availability && !availability.available
        ? t(UNAVAILABLE_KEYS[availability.reason ?? "no_edit_rights"])
        : null,
    texts: {
      heading: t("helper_heading"),
      partnerName: t("helper_partner_name"),
      partnerDescription: t("helper_partner_description"),
      placeholder: t("helper_placeholder"),
      noAccess: t("helper_no_access"),
      newConversationDescription: t("helper_new_conversation_description")
    },
    modes: null,
    refusalText,
    onRefused: (error, title) => {
      const reason = error instanceof EneoApiError ? error.reason : undefined;
      toastApiError(error, t, { title, message: refusalText(reason) ?? undefined });
    },
    references,
    footerActions,
    toolCards: (call) => assistantHelperCardFor(call, assistant.id),
    onToolCallFinished: (call) => {
      if (!isAssistantToolCall(call)) return;
      refresh();
      // A publish also changes whose API keys follow the assistant's, as the
      // publishing section's own publish refreshes.
      if (call.toolName === "publish_assistant") void invalidateExpiringApiKeys(queryClient);
      const change = changeOf(call, assistant.id);
      const fields = change ? changedFields(change.changes) : [];
      if (fields.length > 0) onChanged?.(fields);
    },
    onAnswerFinished: refresh,
    beforeSend
  };
}

/**
 * "Hjälpassistent" in the editor's header: opens and closes the helper
 * beside the settings, pressed while it is open. It follows the availability
 * read: absent while that is pending or failed, for a person who may not
 * edit the assistant or whose role does not give the helper, and for an
 * assistant configured elsewhere; disabled, with
 * the reason, while the space has no model for it. `compact` (a phone's bar)
 * shows the icon alone, its name as a tooltip, and leaves a disabled toggle
 * out: its reason would be only in a tooltip, which a finger cannot reach.
 */
export function AssistantHelperToggle({
  availability,
  open,
  onOpenChange,
  compact = false,
  ref
}: {
  availability: AssistantHelperAvailability | undefined;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  compact?: boolean;
  ref?: Ref<HTMLButtonElement>;
}) {
  const t = useTranslations();
  if (!availability) return null;
  const disabled = !availability.available;
  if (disabled && (compact || availability.reason !== "no_model")) return null;
  return (
    <ToggleButton
      ref={ref}
      label={t("helper_heading")}
      icon={<Sparkles aria-hidden="true" className="size-4" />}
      isIconOnly={compact}
      size="sm"
      isPressed={open && !disabled}
      isDisabled={disabled}
      tooltip={disabled ? t("helper_unavailable_no_model") : undefined}
      onPressedChange={(pressed) => onOpenChange(pressed)}
    />
  );
}

/**
 * "Fråga" at the end of a section's heading row: puts a reference to the
 * section in the helper's composer, opening the helper first. Its name says
 * which section it asks about.
 */
export function AskHelperButton({ section, onAsk }: { section: string; onAsk: () => void }) {
  const t = useTranslations();
  return (
    <Button
      variant="ghost"
      size="sm"
      label={t("helper_ask_about", { section })}
      icon={<MessageSquarePlus aria-hidden="true" className="size-4" />}
      onClick={onAsk}
      className="text-ax-text-secondary hover:text-ax-text"
    >
      {t("helper_ask")}
    </Button>
  );
}
