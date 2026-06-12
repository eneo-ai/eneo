"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useSearchParams } from "next/navigation";
import { useTranslations } from "next-intl";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue
} from "@/components/ui/select";
import { browserApi } from "@/lib/api/browser";
import { unwrap } from "@/lib/api/errors";
import { toastApiError } from "@/lib/api/toast";
import type { ChatPartner } from "@/lib/chat/types";
import { ChatPage } from "@/features/chat/chat-page";
import { useSpace } from "@/features/spaces/use-space";

function toModelInfo(
  model:
    | { id: string; name: string; max_input_tokens: number; vision: boolean; reasoning: boolean }
    | null
    | undefined
) {
  if (!model) return null;
  return {
    id: model.id,
    name: model.name,
    token_limit: model.max_input_tokens,
    vision: model.vision,
    reasoning: model.reasoning
  };
}

/** Default-assistant completion model switcher (personal chat only). */
function ModelSwitcher() {
  const t = useTranslations();
  const { space, routeId } = useSpace();
  const queryClient = useQueryClient();
  const assistant = space.default_assistant;

  const update = useMutation({
    mutationFn: (modelId: string) =>
      unwrap(
        // RB-5(b): assistants use POST-as-update.
        browserApi.POST("/api/v1/assistants/{id}/", {
          params: { path: { id: assistant!.id } },
          body: { completion_model: { id: modelId } }
        })
      ),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["spaces", routeId] }),
    onError: (error) => toastApiError(error, t)
  });

  if (!assistant) return null;

  return (
    <Select
      value={assistant.completion_model?.id ?? ""}
      disabled={update.isPending}
      onValueChange={(modelId) => update.mutate(modelId)}
    >
      <SelectTrigger size="sm" className="w-56" aria-label={t("completion_model")}>
        <SelectValue placeholder={t("choose_a_completion_model")} />
      </SelectTrigger>
      <SelectContent>
        {space.completion_models.map((model) => (
          <SelectItem key={model.id} value={model.id}>
            {model.nickname ?? model.name}
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  );
}

export function SpaceChat() {
  const { space, routeId } = useSpace();
  const searchParams = useSearchParams();

  const type = searchParams.get("type") ?? "default-assistant";
  const partnerId = searchParams.get("id");
  const sessionId = searchParams.get("session_id");

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

  let partner: ChatPartner | null = null;
  if (type === "group-chat" && groupChatQuery.data) {
    const groupChat = groupChatQuery.data;
    partner = {
      type: "group-chat",
      id: groupChat.id,
      name: groupChat.name,
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
      completionModel: toModelInfo(assistant.completion_model)
    };
  } else if (type === "default-assistant" || !partnerId) {
    const assistant = space.default_assistant;
    if (assistant) {
      partner = {
        type: "default-assistant",
        id: assistant.id,
        name: assistant.name,
        completionModel: toModelInfo(assistant.completion_model)
      };
    }
  }

  if (!partner) {
    return (
      <div className="flex flex-1 flex-col gap-3 p-6">
        <Skeleton className="h-10 w-1/3" />
        <Skeleton className="h-32 w-full" />
      </div>
    );
  }

  const base = `/spaces/${routeId}/chat`;
  const query = new URLSearchParams();
  if (type !== "default-assistant") query.set("type", type);
  if (partnerId) query.set("id", partnerId);

  return (
    <ChatPage
      // Remount when the partner changes so chat state never leaks across.
      key={`${partner.type}:${partner.id}`}
      partner={partner}
      initialSessionId={sessionId}
      headerExtra={partner.type === "default-assistant" ? <ModelSwitcher /> : undefined}
      buildSessionUrl={(nextSessionId) => {
        const params = new URLSearchParams(query);
        if (nextSessionId) params.set("session_id", nextSessionId);
        const qs = params.toString();
        return qs ? `${base}?${qs}` : base;
      }}
    />
  );
}
