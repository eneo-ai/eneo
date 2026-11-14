import { notFound } from "@tanstack/react-router";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useSearchParams } from "@/lib/navigation";
import { useTranslations } from "use-intl";
import { ModelSelector } from "@/components/ai-elements/model-selector";
import { useAppContext } from "@/components/providers/app-context";
import { browserApi } from "@/lib/api/browser";
import { unwrap } from "@/lib/api/errors";
import { toastApiError } from "@/lib/api/toast";
import type { ChatPartner } from "@/lib/chat/types";
import { selectEffectiveModelId } from "@/features/ai-models/select-effective-chat-model";
import { ChatPartnerError, ChatPartnerLoading } from "@/features/chat/chat-partner-state";
import { ChatPage } from "@/features/chat/chat-page";
import { partnerCompletionModel } from "@/features/chat/partner-model";
import { chatPartnerSwitcherItems } from "@/features/chat/partner-switcher";
import { partnerKnowledge } from "@/features/chat/partner-knowledge";
import { queuePartnerUpdate } from "@/features/chat/partner-updates";
import { ModelReasoningPicker } from "@/features/chat/model-reasoning-picker";
import { personalChatSkillsConfigurationQueryOptions } from "@/features/skills/personal-chat-skills";
import { useSpace } from "@/features/spaces/use-space";

/** The composer's compact (ghost) trigger look of the model picker. */
const COMPOSER_PICKER_CLASS =
  "text-ax-text-secondary hover:text-ax-text rounded-ax-element h-8 border-0 px-2 text-[13px] font-semibold pointer-coarse:h-11 pointer-coarse:min-w-11";

/**
 * The personal chat's model and reasoning-level choices, with their saves.
 * Both are stored on the personal space's default assistant, a global change
 * (see the "personal chat model is global" contract): the model as
 * `completion_model`, the level as `completion_model_kwargs.reasoning_effort`
 * (null = the organisation default), exactly as the Svelte app does. The
 * backend reads them from the stored assistant when it answers, so nothing
 * travels with the question itself. The admin governance policy is honoured:
 * a pinned model is locked, an enforced allow-list filters the list, and the
 * effective pick is resolved when the saved one is disallowed.
 */
function usePersonalChatModel() {
  const t = useTranslations();
  const { space, routeId } = useSpace();
  const queryClient = useQueryClient();
  const assistant = space.default_assistant;
  const config = assistant?.effective_config ?? null;

  const update = useMutation({
    mutationFn: (
      body:
        | { completion_model: { id: string } }
        | { completion_model_kwargs: { reasoning_effort: string | null } }
    ) =>
      queuePartnerUpdate(() =>
        unwrap(
          // RB-5(b): assistants use POST-as-update.
          browserApi.POST("/api/v1/assistants/{id}/", {
            params: { path: { id: assistant!.id } },
            body
          })
        )
      ),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["spaces", routeId] }),
    onError: (error) => toastApiError(error, t)
  });

  if (!assistant) return null;

  const lockedModel =
    config?.models_enforced && config.locked_model
      ? (space.completion_models.find((model) => model.id === config.locked_model!.id) ??
        config.locked_model)
      : null;
  const allowedIds = config?.models_enforced
    ? new Set(config.available_models.map((model) => model.id))
    : null;

  return {
    models: allowedIds
      ? space.completion_models.filter((model) => allowedIds.has(model.id))
      : space.completion_models,
    selectedId:
      selectEffectiveModelId(assistant.completion_model?.id, config) ??
      assistant.completion_model?.id ??
      null,
    lockedModel,
    // The picker shows the new choice while it saves and keeps focus; a
    // disabled trigger would drop focus to the page.
    selectModel: (id: string) => update.mutateAsync({ completion_model: { id } }),
    /** Whether the governance policy lets people choose the reasoning level. */
    levelConfigurable: config?.reasoning_effort_user_configurable ?? false,
    storedLevel: assistant.completion_model_kwargs?.reasoning_effort ?? null,
    policyDefaultLevel: config?.default_reasoning_effort ?? null,
    selectLevel: (effort: string | null) =>
      update.mutateAsync({ completion_model_kwargs: { reasoning_effort: effort } })
  };
}

/**
 * The personal assistant's composer picker: the model, and in the same
 * control the reasoning level where the governance policy lets people choose it.
 */
function ComposerPickers() {
  const { tenant } = useAppContext();
  const choice = usePersonalChatModel();
  if (!choice) return null;

  if (choice.levelConfigurable) {
    return (
      <ModelReasoningPicker
        models={choice.models}
        selectedId={choice.selectedId}
        onSelectModel={choice.selectModel}
        locked={choice.lockedModel}
        showPricing={tenant.show_model_pricing}
        storedLevel={choice.storedLevel}
        policyDefaultLevel={choice.policyDefaultLevel}
        onSelectLevel={choice.selectLevel}
      />
    );
  }
  return (
    <ModelSelector
      models={choice.models}
      selectedId={choice.selectedId}
      onSelect={choice.selectModel}
      locked={choice.lockedModel}
      size="sm"
      showPricing={tenant.show_model_pricing}
      className={COMPOSER_PICKER_CLASS}
    />
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
