"use client";

import { useQuery } from "@tanstack/react-query";
import { useSearchParams } from "next/navigation";
import { useEffect } from "react";
import { useTranslations } from "next-intl";
import { browserApi } from "@/lib/api/browser";
import { unwrap } from "@/lib/api/errors";
import type { ChatPartner } from "@/lib/chat/types";
import {
  ChatPartnerError,
  ChatPartnerLoading,
  retryPartnerQuery
} from "@/features/chat/chat-partner-state";
import { ChatPage } from "@/features/chat/chat-page";
import { partnerCompletionModel } from "@/features/chat/partner-model";
import { authoringAssistantQueryOptions, flowQueryOptions } from "@/features/flows/flows";
import { FlowPanelProvider, useFlowPanel } from "@/features/flows/use-flow-panel";
import { useSpace } from "@/features/spaces/use-space";

/**
 * Keeps the address at the flow: a page opened as `/flows/new` moves to
 * `/flows/<id>` once the first flows tool call has named the flow it made.
 * A shallow history update, like the chat's session id: a router navigation
 * would remount the chat mid-answer.
 */
function FlowAddress({ routeId, routeFlowId }: { routeId: string; routeFlowId: string | null }) {
  const store = useFlowPanel();
  const boundFlowId = store?.flowId ?? null;
  useEffect(() => {
    if (routeFlowId !== null || boundFlowId === null) return;
    const url = new URL(window.location.href);
    url.pathname = `/spaces/${routeId}/flows/${boundFlowId}`;
    window.history.replaceState(null, "", url);
  }, [routeId, routeFlowId, boundFlowId]);
  return null;
}

export function FlowChat({ flowId }: { flowId: string | null }) {
  const t = useTranslations();
  const { space, routeId } = useSpace();
  const searchParams = useSearchParams();
  const runId = searchParams.get("run");
  const tab = searchParams.get("tab") === "runs" ? "runs" : null;

  const flowQuery = useQuery({
    ...flowQueryOptions(flowId ?? ""),
    enabled: flowId !== null,
    retry: retryPartnerQuery
  });
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
  const partner: ChatPartner | null = assistant
    ? {
        type: "assistant",
        id: assistant.id,
        name: t("flows_assistant_name"),
        allowedAttachments: assistant.allowed_attachments,
        insightEnabled: false,
        description: t("flows_assistant_description"),
        iconId: assistant.icon_id ?? null,
        knowledge: [],
        spaceName,
        personalSpace: space.personal,
        securityClassification: space.security_classification?.name ?? null,
        mcpServers: assistant.mcp_servers ?? [],
        enabledCapabilities: assistant.enabled_capabilities,
        availableCapabilities: assistant.available_capabilities,
        effectiveConfig: assistant.effective_config ?? null,
        completionModel: partnerCompletionModel(assistant, space.completion_models)
      }
    : null;

  const queries = [authoringQuery, assistantQuery, ...(flowId !== null ? [flowQuery] : [])];
  const failed = queries.find((query) => query.isError);
  if (failed) return <ChatPartnerError onRetry={() => void failed.refetch()} />;
  if (!partner || (flowId !== null && !flowQuery.data)) return <ChatPartnerLoading />;

  return (
    <FlowPanelProvider flowId={flowId} runId={runId} tab={tab}>
      <FlowAddress routeId={routeId} routeFlowId={flowId} />
      <ChatPage
        // One chat per flow; the key stays while the address moves from "new" to the id.
        key={`flow:${flowId ?? "new"}`}
        partner={partner}
        sessionId={flowQuery.data?.conversation_id ?? null}
        singleConversation
      />
    </FlowPanelProvider>
  );
}
