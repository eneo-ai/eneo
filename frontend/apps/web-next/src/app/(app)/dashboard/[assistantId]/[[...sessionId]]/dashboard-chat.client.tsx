"use client";

import { useQuery } from "@tanstack/react-query";
import { LoadingState } from "@/components/composites/loading-state";
import { browserApi } from "@/lib/api/browser";
import { unwrap } from "@/lib/api/errors";
import type { ChatPartner } from "@/lib/chat/types";
import { ChatPage } from "@/features/chat/chat-page";
import { partnerKnowledge } from "@/features/chat/partner-knowledge";

export function DashboardChat({
  assistantId,
  sessionId
}: {
  assistantId: string;
  sessionId: string | null;
}) {
  const { data: assistant } = useQuery({
    queryKey: ["assistants", assistantId],
    queryFn: () =>
      unwrap(browserApi.GET("/api/v1/assistants/{id}/", { params: { path: { id: assistantId } } }))
  });

  if (!assistant) {
    return (
      <div className="mx-auto w-full max-w-[712px] p-6">
        <LoadingState rows={4} />
      </div>
    );
  }

  const partner: ChatPartner = {
    type: "assistant",
    id: assistant.id,
    name: assistant.name,
    allowedAttachments: assistant.allowed_attachments,
    insightEnabled: assistant.insight_enabled,
    description: assistant.description ?? null,
    iconId: assistant.icon_id ?? null,
    knowledge: partnerKnowledge(assistant),
    mcpServers: assistant.mcp_servers ?? [],
    enabledCapabilities: assistant.enabled_capabilities,
    availableCapabilities: assistant.available_capabilities,
    effectiveConfig: assistant.effective_config ?? null,
    completionModel: assistant.completion_model
      ? {
          id: assistant.completion_model.id,
          name: assistant.completion_model.name,
          token_limit: assistant.completion_model.max_input_tokens,
          vision: assistant.completion_model.vision,
          reasoning: assistant.completion_model.reasoning
        }
      : null
  };

  return (
    <ChatPage
      partner={partner}
      sessionId={sessionId}
      buildSessionUrl={(nextSessionId) =>
        nextSessionId ? `/dashboard/${assistantId}/${nextSessionId}` : `/dashboard/${assistantId}`
      }
    />
  );
}
