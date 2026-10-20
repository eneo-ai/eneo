"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useSearchParams } from "next/navigation";
import { useTranslations } from "next-intl";
import { ModelSelector } from "@/components/ai-elements/model-selector";
import { useAppContext } from "@/components/providers/app-context";
import { browserApi } from "@/lib/api/browser";
import { unwrap } from "@/lib/api/errors";
import { toastApiError } from "@/lib/api/toast";
import type { ChatPartner } from "@/lib/chat/types";
import type { Schema } from "@/lib/api/models";
import { selectEffectiveModelId } from "@/features/ai-models/select-effective-chat-model";
import {
  ChatPartnerError,
  ChatPartnerLoading,
  retryPartnerQuery
} from "@/features/chat/chat-partner-state";
import { ChatPage } from "@/features/chat/chat-page";
import { partnerCompletionModel } from "@/features/chat/partner-model";
import { trackPartnerUpdate } from "@/features/chat/partner-updates";
import { bindFlowConversation } from "@/features/flows/flow-create";
import { authoringAssistantQueryOptions, flowQueryOptions } from "@/features/flows/flows";
import { FlowPanelProvider } from "@/features/flows/use-flow-panel";
import { useSpace } from "@/features/spaces/use-space";

/** The composer's compact (ghost) trigger look, as the personal chat's model picker. */
const COMPOSER_PICKER_CLASS =
  "text-ax-text-secondary hover:text-ax-text rounded-ax-element h-8 border-0 px-2 text-[13px] font-semibold pointer-coarse:h-11";

type AuthoringAssistant = Schema<"AssistantPublic">;

/**
 * The model the flows assistant answers with, chosen in the composer and
 * saved on the hidden authoring assistant of the space (one choice for
 * everyone building flows there). A governance policy that pins a model
 * shows it locked; an enforced allow-list narrows the choice.
 */
function FlowsModelSwitcher({ assistant }: { assistant: AuthoringAssistant }) {
  const t = useTranslations();
  const { space } = useSpace();
  const { tenant } = useAppContext();
  const queryClient = useQueryClient();
  const config = assistant.effective_config ?? null;

  const update = useMutation({
    mutationFn: (modelId: string) =>
      trackPartnerUpdate(
        unwrap(
          browserApi.POST("/api/v1/assistants/{id}/", {
            params: { path: { id: assistant.id } },
            body: { completion_model: { id: modelId } }
          })
        )
      ),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["assistants", assistant.id] }),
    onError: (error) => toastApiError(error, t)
  });

  const lockedModel =
    config?.models_enforced && config.locked_model
      ? (space.completion_models.find((model) => model.id === config.locked_model!.id) ??
        config.locked_model)
      : null;
  const allowedIds = config?.models_enforced
    ? new Set(config.available_models.map((model) => model.id))
    : null;
  const visibleModels = allowedIds
    ? space.completion_models.filter((model) => allowedIds.has(model.id))
    : space.completion_models;
  const selectedId =
    selectEffectiveModelId(assistant.completion_model?.id, config) ??
    assistant.completion_model?.id ??
    null;

  return (
    <ModelSelector
      models={visibleModels}
      selectedId={selectedId}
      onSelect={(id) => update.mutateAsync(id)}
      locked={lockedModel}
      size="sm"
      showPricing={tenant.show_model_pricing}
      className={COMPOSER_PICKER_CLASS}
    />
  );
}

export function FlowChat({ flowId }: { flowId: string }) {
  const t = useTranslations();
  const { space, can } = useSpace();
  const queryClient = useQueryClient();
  const searchParams = useSearchParams();
  const runId = searchParams.get("run");
  const tab = searchParams.get("tab") === "runs" ? "runs" : null;

  const flowQuery = useQuery({ ...flowQueryOptions(flowId), retry: retryPartnerQuery });
  const authoringQuery = useQuery({
    ...authoringAssistantQueryOptions(space.id),
    retry: retryPartnerQuery
  });
  const assistantId = authoringQuery.data?.assistant_id ?? null;
  const assistantQuery = useQuery({
    queryKey: ["assistants", assistantId],
    enabled: assistantId !== null,
    queryFn: () =>
      unwrap(
        browserApi.GET("/api/v1/assistants/{id}/", { params: { path: { id: assistantId! } } })
      ),
    retry: retryPartnerQuery
  });

  const spaceName = space.personal ? t("personal") : space.name;
  const assistant = assistantQuery.data;
  // The chat is about one flow: it is named after it, with the assistant and
  // the space as the line beneath.
  const partner: ChatPartner | null = assistant
    ? {
        type: "assistant",
        id: assistant.id,
        name: flowQuery.data?.name ?? t("flows_assistant_name"),
        allowedAttachments: assistant.allowed_attachments,
        insightEnabled: false,
        description: t("flows_assistant_description"),
        iconId: assistant.icon_id ?? null,
        knowledge: [],
        spaceName: `${t("flows_assistant_name")} · ${spaceName}`,
        personalSpace: space.personal,
        securityClassification: space.security_classification?.name ?? null,
        mcpServers: assistant.mcp_servers ?? [],
        enabledCapabilities: assistant.enabled_capabilities,
        availableCapabilities: assistant.available_capabilities,
        effectiveConfig: assistant.effective_config ?? null,
        completionModel: partnerCompletionModel(assistant, space.completion_models)
      }
    : null;

  const queries = [authoringQuery, assistantQuery, flowQuery];
  const failed = queries.find((query) => query.isError);
  if (failed) return <ChatPartnerError onRetry={() => void failed.refetch()} />;
  if (!partner || !flowQuery.data) return <ChatPartnerLoading />;

  return (
    <FlowPanelProvider flowId={flowId} runId={runId} tab={tab}>
      <ChatPage
        key={`flow:${flowId}`}
        partner={partner}
        sessionId={flowQuery.data.conversation_id ?? null}
        onSessionCreated={(sessionId) => {
          // The chat that just started is this flow's chat from now on.
          bindFlowConversation(flowId, sessionId)
            .then(() =>
              queryClient.invalidateQueries({ queryKey: flowQueryOptions(flowId).queryKey })
            )
            .catch((error: unknown) => toastApiError(error, t));
        }}
        modelSelector={
          can("edit", "flow") && assistant ? (
            <FlowsModelSwitcher assistant={assistant} />
          ) : undefined
        }
        singleConversation
      />
    </FlowPanelProvider>
  );
}
