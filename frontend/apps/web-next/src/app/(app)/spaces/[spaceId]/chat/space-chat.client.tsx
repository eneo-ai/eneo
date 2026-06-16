"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Pencil } from "lucide-react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { useTranslations } from "next-intl";
import { ModelSelector } from "@/components/ai-elements/model-selector";
import { useAppContext } from "@/components/providers/app-context";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { browserApi } from "@/lib/api/browser";
import { unwrap } from "@/lib/api/errors";
import { toastApiError } from "@/lib/api/toast";
import type { ChatPartner } from "@/lib/chat/types";
import { selectEffectiveModelId } from "@/features/ai-models/select-effective-chat-model";
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

/**
 * Default-assistant completion model switcher (personal chat only). Switching
 * persists on the personal space's default assistant — a global change (see the
 * "personal chat model is global" contract) — and honours the admin governance
 * policy: a pinned model shows a locked label, an enforced allow-list filters
 * the list, and the effective pick is resolved when the saved one is disallowed.
 */
function ModelSwitcher() {
  const t = useTranslations();
  const { space, routeId } = useSpace();
  const { tenant } = useAppContext();
  const queryClient = useQueryClient();
  const assistant = space.default_assistant;
  const config = assistant?.effective_config ?? null;

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
      onSelect={(id) => update.mutate(id)}
      locked={lockedModel}
      disabled={update.isPending}
      size="sm"
      showPricing={tenant.show_model_pricing}
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
      initialSessionId={sessionId}
      modelSelector={partner.type === "default-assistant" ? <ModelSwitcher /> : undefined}
      actions={
        editHref ? (
          <Button asChild variant="outline" size="sm">
            <Link href={editHref}>
              <Pencil className="size-4" />
              <span className="hidden sm:inline">{t("edit")}</span>
            </Link>
          </Button>
        ) : undefined
      }
      buildSessionUrl={(nextSessionId) => {
        const params = new URLSearchParams(query);
        if (nextSessionId) params.set("session_id", nextSessionId);
        const qs = params.toString();
        return qs ? `${base}?${qs}` : base;
      }}
    />
  );
}
