"use client";

import { Dialog, DialogHeader } from "@astryxdesign/core/Dialog";
import { Button } from "@astryxdesign/core/Button";
import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { useSearchParams } from "next/navigation";
import { useTranslations } from "next-intl";
import { ModelSelector } from "@/components/ai-elements/model-selector";
import { useAppContext } from "@/components/providers/app-context";
import { browserApi } from "@/lib/api/browser";
import { unwrap } from "@/lib/api/errors";
import type { ChatPartner } from "@/lib/chat/types";
import {
  ChatPartnerError,
  ChatPartnerLoading,
  retryPartnerQuery
} from "@/features/chat/chat-partner-state";
import { ChatPage } from "@/features/chat/chat-page";
import { ChatSkills } from "@/features/chat/chat-skills";
import { partnerCompletionModel } from "@/features/chat/partner-model";
import { chatPartnerSwitcherItems } from "@/features/chat/partner-switcher";
import { partnerKnowledge } from "@/features/chat/partner-knowledge";
import { useConversationSettings } from "@/features/chat/conversation-settings";
import { ReasoningEffortSelector } from "@/features/chat/reasoning-selector";
import { useSpace } from "@/features/spaces/use-space";

/** The composer's compact (ghost) trigger look, shared by the model and reasoning pickers. */
const COMPOSER_PICKER_CLASS =
  "text-ax-text-secondary hover:text-ax-text rounded-ax-element h-8 border-0 px-2 text-[13px] font-semibold pointer-coarse:h-11";

function ModelSwitcher() {
  const { tenant } = useAppContext();
  const { resolution, update, busy, running, hasMessages } = useConversationSettings();
  const t = useTranslations();
  const [pendingId, setPendingId] = useState<string | null>(null);
  const models = resolution?.available_models ?? [];
  return (
    <>
      <ModelSelector
        models={models}
        selectedId={
          resolution?.settings.completion_model_id ?? resolution?.effective_model?.id ?? null
        }
        onSelect={(id) => {
          if (hasMessages) setPendingId(id);
          else return update({ completion_model_id: id, reasoning_effort: null });
        }}
        disabled={busy || running || !resolution || resolution.settings_compatible === false}
        size="sm"
        showPricing={tenant.show_model_pricing}
        className={COMPOSER_PICKER_CLASS}
      />
      <Dialog
        isOpen={pendingId !== null}
        onOpenChange={(open) => {
          if (!open) setPendingId(null);
        }}
      >
        <DialogHeader title={t("personal_chat_model_change_title")} />
        <p>{t("personal_chat_model_change_description")}</p>
        <div className="mt-4 flex justify-end gap-2">
          <Button label={t("cancel")} variant="secondary" onClick={() => setPendingId(null)} />
          <Button
            label={t("personal_chat_model_change_anyway")}
            onClick={() => {
              if (pendingId)
                void update({ completion_model_id: pendingId, reasoning_effort: null });
              setPendingId(null);
            }}
          />
        </div>
      </Dialog>
    </>
  );
}

function ReasoningSwitcher() {
  const { resolution, update, busy, running } = useConversationSettings();
  const options = resolution?.reasoning_effort_options ?? [];
  if (options.length === 0) return null;
  return (
    <fieldset disabled={busy || running || resolution?.settings_compatible === false}>
      <ReasoningEffortSelector
        options={options}
        stored={resolution?.settings.reasoning_effort ?? null}
        policyDefault={resolution?.default_reasoning_effort ?? null}
        onSelect={(effort) => update({ reasoning_effort: effort })}
        className={COMPOSER_PICKER_CLASS}
      />
    </fieldset>
  );
}

/** The personal assistant's composer pickers: model, then reasoning effort when the model offers it. */
function ComposerPickers() {
  return (
    <span className="flex min-w-0 items-center gap-0.5">
      <ModelSwitcher />
      <ReasoningSwitcher />
    </span>
  );
}

export function SpaceChat() {
  const t = useTranslations();
  const { space, routeId } = useSpace();
  const searchParams = useSearchParams();

  const type = searchParams.get("type") ?? "default-assistant";
  const partnerId = searchParams.get("id");
  const sessionId = searchParams.get("session_id");

  const assistantQuery = useQuery({
    queryKey: ["assistants", partnerId],
    enabled: type === "assistant" && partnerId !== null,
    queryFn: () =>
      unwrap(browserApi.GET("/api/v1/assistants/{id}/", { params: { path: { id: partnerId! } } })),
    retry: retryPartnerQuery
  });

  const groupChatQuery = useQuery({
    queryKey: ["group-chats", partnerId],
    enabled: type === "group-chat" && partnerId !== null,
    queryFn: () =>
      unwrap(browserApi.GET("/api/v1/group-chats/{id}/", { params: { path: { id: partnerId! } } })),
    retry: retryPartnerQuery
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
      iconId: groupChat.icon_id ?? null,
      ...spaceInfo,
      showResponseLabel: groupChat.show_response_label,
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
      description: assistant.description ?? null,
      iconId: assistant.icon_id ?? null,
      knowledge: partnerKnowledge(assistant),
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
        ...spaceInfo,
        mcpServers: assistant.mcp_servers ?? [],
        enabledCapabilities: assistant.enabled_capabilities,
        availableCapabilities: assistant.available_capabilities,
        effectiveConfig: assistant.effective_config ?? null,
        completionModel: partnerCompletionModel(assistant, space.completion_models)
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
      skills={partner.type === "default-assistant" && space.personal ? <ChatSkills /> : undefined}
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
