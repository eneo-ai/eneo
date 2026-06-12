"use client";

import { useQuery } from "@tanstack/react-query";
import { Skeleton } from "@/components/ui/skeleton";
import { browserApi } from "@/lib/api/browser";
import { unwrap } from "@/lib/api/errors";
import type { ChatPartner } from "@/lib/chat/types";
import { ChatPage } from "@/features/chat/chat-page";

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
      <div className="flex flex-1 flex-col gap-3 p-6">
        <Skeleton className="h-10 w-1/3" />
        <Skeleton className="h-32 w-full" />
      </div>
    );
  }

  const partner: ChatPartner = {
    type: "assistant",
    id: assistant.id,
    name: assistant.name,
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
      initialSessionId={sessionId}
      buildSessionUrl={(nextSessionId) =>
        nextSessionId ? `/dashboard/${assistantId}/${nextSessionId}` : `/dashboard/${assistantId}`
      }
    />
  );
}
