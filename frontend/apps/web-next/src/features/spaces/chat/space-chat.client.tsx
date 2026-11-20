import { Dialog, DialogHeader } from "@astryxdesign/core/Dialog";
import { Button } from "@astryxdesign/core/Button";
import { useId, useRef, useState } from "react";
import { notFound } from "@tanstack/react-router";
import { useQuery } from "@tanstack/react-query";
import { useSearchParams } from "@/lib/navigation";
import { useTranslations } from "use-intl";
import { useAppContext } from "@/components/providers/app-context";
import { browserApi } from "@/lib/api/browser";
import { unwrap } from "@/lib/api/errors";
import { useFocusRescue } from "@/lib/focus-rescue";
import type { ChatPartner } from "@/lib/chat/types";
import { ChatPartnerError, ChatPartnerLoading } from "@/features/chat/chat-partner-state";
import { ChatPage } from "@/features/chat/chat-page";
import { partnerCompletionModel } from "@/features/chat/partner-model";
import { chatPartnerSwitcherItems } from "@/features/chat/partner-switcher";
import { partnerKnowledge } from "@/features/chat/partner-knowledge";
import { useConversationSettings } from "@/features/chat/conversation-settings";
import { queuePartnerUpdate } from "@/features/chat/partner-updates";
import { ModelReasoningPicker } from "@/features/chat/model-reasoning-picker";
import { personalChatSkillsConfigurationQueryOptions } from "@/features/skills/personal-chat-skills";
import { useSpace } from "@/features/spaces/use-space";

function ComposerPickers() {
  const { tenant } = useAppContext();
  const { choiceScope, resolution, update, running, hasMessages, startConversation } =
    useConversationSettings();
  const t = useTranslations();
  const [pendingId, setPendingId] = useState<string | null>(null);
  const waitMessageId = useId();
  const trigger = useRef<HTMLButtonElement>(null);
  const rescue = useFocusRescue();
  const restoreTrigger = () => rescue(() => trigger.current);
  const close = () => {
    setPendingId(null);
    restoreTrigger();
  };
  if (!resolution) return null;
  const modelChoice = (id: string) => ({ completion_model_id: id, reasoning_effort: null });

  return (
    <>
      <ModelReasoningPicker
        ownerId={choiceScope}
        models={resolution.available_models ?? []}
        selectedId={
          resolution.settings.completion_model_id ?? resolution.effective_model?.id ?? null
        }
        locked={resolution.model_locked ? (resolution.effective_model ?? null) : null}
        showPricing={tenant.show_model_pricing}
        storedLevel={resolution.settings.reasoning_effort ?? null}
        policyDefaultLevel={resolution.default_reasoning_effort ?? null}
        currentReasoningOptions={resolution.reasoning_effort_options ?? []}
        levelConfigurable={resolution.reasoning_effort_user_configurable ?? false}
        triggerRef={trigger}
        disabled={running || resolution.settings_compatible === false}
        resetLevelOnModelChange
        onModelChoice={(id) => {
          if (!hasMessages) return true;
          setPendingId(id);
          return false;
        }}
        onSave={({ modelId, level }) =>
          update(
            modelId
              ? { ...modelChoice(modelId), reasoning_effort: level ?? null }
              : { reasoning_effort: level }
          )
        }
      />
      <Dialog
        isOpen={pendingId !== null}
        onOpenChange={(open) => {
          if (!open) close();
        }}
      >
        <DialogHeader title={t("personal_chat_model_change_title")} />
        <p>{t("personal_chat_model_change_description")}</p>
        {running && (
          <p id={waitMessageId} className="text-ax-text-secondary mt-2 text-sm">
            {t("personal_chat_model_change_wait")}
          </p>
        )}
        <div className="mt-4 flex flex-wrap justify-end gap-2">
          <Button label={t("cancel")} variant="secondary" onClick={close} />
          <Button
            label={t("personal_chat_model_change_anyway")}
            variant="secondary"
            aria-disabled={running || undefined}
            aria-describedby={running ? waitMessageId : undefined}
            onClick={() => {
              if (!pendingId || running) return;
              void queuePartnerUpdate(() => update(modelChoice(pendingId)));
              close();
            }}
          />
          {startConversation && (
            <Button
              label={t("personal_chat_model_new_conversation")}
              onClick={() => {
                if (pendingId) startConversation(modelChoice(pendingId), restoreTrigger);
                setPendingId(null);
              }}
            />
          )}
        </div>
      </Dialog>
    </>
  );
}

export function SpaceChat() {
  const t = useTranslations();
  const { space, routeId } = useSpace();
  const searchParams = useSearchParams();

  const type = searchParams.get("type") ?? "default-assistant";
  const partnerId = searchParams.get("id");
  const sessionId = searchParams.get("session_id");

  const defaultAssistant = space.default_assistant;
  const defaultModel = defaultAssistant
    ? partnerCompletionModel(defaultAssistant, space.completion_models)
    : null;
  const personalConfiguration = useQuery({
    ...personalChatSkillsConfigurationQueryOptions({
      spaceId: space.id,
      assistantId: defaultAssistant?.id ?? null,
      modelId: defaultAssistant?.completion_model?.id ?? null
    }),
    enabled:
      space.personal &&
      (type === "default-assistant" || !partnerId) &&
      Boolean(defaultAssistant?.permissions?.includes("read"))
  });

  const assistantQuery = useQuery({
    queryKey: ["assistants", partnerId],
    enabled: type === "assistant" && partnerId !== null,
    queryFn: () =>
      unwrap(browserApi.GET("/api/v1/assistants/{id}/", { params: { path: { id: partnerId! } } }))
  });

  const groupChatQuery = useQuery({
    queryKey: ["group-chats", partnerId],
    enabled: type === "group-chat" && partnerId !== null,
    queryFn: () =>
      unwrap(browserApi.GET("/api/v1/group-chats/{id}/", { params: { path: { id: partnerId! } } }))
  });
  // The query that loads a non-default partner (null for the space's own assistant).
  const partnerQuery =
    partnerId === null
      ? null
      : type === "assistant"
        ? assistantQuery
        : type === "group-chat"
          ? groupChatQuery
          : null;

  if (type === "assistant" && assistantQuery.data?.is_help_assistant) throw notFound();

  const spaceName = space.personal
    ? t("personal")
    : space.organization
      ? t("organization")
      : space.name;
  const spaceInfo = {
    spaceName,
    personalSpace: space.personal,
    securityClassification: space.security_classification?.name ?? null
  };

  let partner: ChatPartner | null = null;
  if (type === "group-chat" && groupChatQuery.data) {
    const groupChat = groupChatQuery.data;
    partner = {
      type: "group-chat",
      id: groupChat.id,
      name: groupChat.name,
      allowedAttachments: groupChat.allowed_attachments,
      insightEnabled: groupChat.insight_enabled,
      permissions: groupChat.permissions,
      iconId: groupChat.icon_id ?? null,
      ...spaceInfo,
      showResponseLabel: groupChat.show_response_label,
      assistantCount: groupChat.tools.assistants.length,
      mentionableAssistants: groupChat.allow_mentions
        ? groupChat.tools.assistants.map((assistant) => ({
            id: assistant.id,
            handle: assistant.handle
          }))
        : []
    };
  } else if (type === "assistant" && assistantQuery.data) {
    const assistant = assistantQuery.data;
    partner = {
      type: "assistant",
      id: assistant.id,
      name: assistant.name,
      allowedAttachments: assistant.allowed_attachments,
      insightEnabled: assistant.insight_enabled,
      permissions: assistant.permissions,
      description: assistant.description ?? null,
      iconId: assistant.icon_id ?? null,
      knowledge: partnerKnowledge(assistant),
      knowledgeMode: assistant.knowledge_mode,
      ...spaceInfo,
      mcpServers: assistant.mcp_servers ?? [],
      enabledCapabilities: assistant.enabled_capabilities,
      availableCapabilities: assistant.available_capabilities,
      effectiveConfig: assistant.effective_config ?? null,
      completionModel: partnerCompletionModel(assistant, space.completion_models)
    };
  } else if (type === "default-assistant" || !partnerId) {
    const assistant = space.default_assistant;
    if (assistant) {
      partner = {
        type: "default-assistant",
        id: assistant.id,
        name: assistant.name,
        allowedAttachments: assistant.allowed_attachments,
        insightEnabled: false,
        iconId: assistant.icon_id ?? null,
        knowledge: partnerKnowledge(assistant),
        knowledgeMode: assistant.knowledge_mode,
        ...spaceInfo,
        mcpServers: assistant.mcp_servers ?? [],
        enabledCapabilities: assistant.enabled_capabilities,
        availableCapabilities: assistant.available_capabilities,
        effectiveConfig: assistant.effective_config ?? null,
        completionModel: defaultModel,
        preflightRevision: JSON.stringify([
          defaultModel?.id ?? null,
          personalConfiguration.dataUpdatedAt
        ])
      };
    }
  }

  if (!partner) {
    if (partnerQuery?.isPending) return <ChatPartnerLoading />;
    // A failed load can be retried; a space without its default assistant or
    // an unknown partner type can't.
    return (
      <ChatPartnerError
        onRetry={partnerQuery?.isError ? () => void partnerQuery.refetch() : undefined}
      />
    );
  }

  if (
    partner.type === "default-assistant" &&
    !space.default_assistant?.permissions?.includes("read")
  ) {
    return (
      <div className="mx-auto flex w-full max-w-[712px] flex-col gap-3 p-6">
        <h1 className="text-lg font-semibold">{t("personal_chat_no_access_title")}</h1>
        <p className="text-ax-text-secondary text-sm">{t("personal_chat_no_access_description")}</p>
      </div>
    );
  }

  const base = `/spaces/${routeId}/chat`;
  const query = new URLSearchParams();
  if (type !== "default-assistant") query.set("type", type);
  if (partnerId) query.set("id", partnerId);

  // Jump straight to the editor from the chat header (the Svelte app's
  // in-context Edit button); gated on the partner's own edit permission.
  const editHref =
    type === "assistant" && assistantQuery.data?.permissions?.includes("edit")
      ? `/spaces/${routeId}/assistants/${partner.id}/edit`
      : type === "group-chat" && groupChatQuery.data?.permissions?.includes("edit")
        ? `/spaces/${routeId}/group-chats/${partner.id}/edit`
        : null;

  return (
    <ChatPage
      // Remount when the partner changes so chat state never leaks across.
      key={`${partner.type}:${partner.id}`}
      partner={partner}
      sessionId={sessionId}
      switcherItems={chatPartnerSwitcherItems({
        space,
        routeId,
        activeType: partner.type,
        activeId: partner.id
      })}
      modelSelector={partner.type === "default-assistant" ? <ComposerPickers /> : undefined}
      withSkills={partner.type === "default-assistant" && space.personal}
      editHref={editHref}
      buildSessionUrl={(nextSessionId) => {
        const params = new URLSearchParams(query);
        if (nextSessionId) params.set("session_id", nextSessionId);
        const qs = params.toString();
        return qs ? `${base}?${qs}` : base;
      }}
    />
  );
}
