import { useIsMutating, useQuery } from "@tanstack/react-query";
import { useTranslations, useFormatter } from "use-intl";
import { ContextBudget } from "@/components/composites/context-budget";
import { Button } from "@astryxdesign/core/Button";
import { useDebouncedValue } from "@/lib/hooks/use-debounced-value";
import { browserApi } from "@/lib/api/browser";
import { unwrap } from "@/lib/api/errors";
import type { Schema } from "@/lib/api/models";
import { useAnnounceChange } from "@/lib/hooks/use-announce-change";
import { cn } from "@/lib/utils";

export function AssistantContextMeter({
  assistantId,
  prompt,
  attachments,
  model,
  modelConfirmed = true,
  revision
}: {
  assistantId: string;
  prompt?: string;
  attachments: Schema<"AssistantAttachmentInput">[];
  model: Pick<Schema<"CompletionModelPublic">, "id" | "token_limit"> | null;
  modelConfirmed?: boolean;
  revision?: string | null;
}) {
  const t = useTranslations();
  const format = useFormatter();
  // Every writer uses this existing scope. A baseline must not race a model,
  // attachment or Skill change that the server has not confirmed yet.
  const saving = useIsMutating({
    predicate: (mutation) => mutation.options.scope?.id === `assistant:${assistantId}`
  });
  const body = {
    assistant_id: assistantId,
    question: "",
    file_ids: [],
    ...(prompt === undefined ? {} : { assistant_prompt: prompt }),
    attachments: attachments.map((file) => ({ id: file.id, inline_text: file.inline_text ?? true }))
  } satisfies Schema<"PreflightRequest">;
  const key = JSON.stringify([
    body,
    model?.id,
    model?.token_limit,
    revision,
    modelConfirmed,
    saving > 0
  ]);
  const debounced = useDebouncedValue(key, 400);
  const enabled = !!model?.token_limit && modelConfirmed && saving === 0 && key === debounced;
  const query = useQuery({
    queryKey: ["assistant-material-preflight", key],
    queryFn: ({ signal }) =>
      unwrap(browserApi.POST("/api/v1/conversations/preflight", { body, signal })),
    enabled,
    retry: false,
    gcTime: 0,
    staleTime: 0,
    refetchOnWindowFocus: false
  });
  const used = query.data ? query.data.file_tokens + (query.data.prompt_tokens ?? 0) : 0;
  const reserve = query.data?.context_reserve_tokens ?? 0;
  const ceiling = Math.max(0, (model?.token_limit ?? 0) - reserve);
  const variant = used > ceiling ? "error" : used > ceiling * 0.8 ? "warning" : "neutral";
  const warning =
    variant === "neutral"
      ? null
      : t(variant === "error" ? "config_attachment_meter_over_budget" : "assistant_context_near");
  useAnnounceChange(
    enabled && !query.isFetching
      ? query.isError
        ? t("assistant_context_unavailable")
        : warning
      : null
  );
  if (!enabled || !model) return null;
  if (query.isError)
    return (
      <div className="text-ax-text-secondary flex flex-wrap items-center gap-2 text-sm">
        <p>{t("assistant_context_unavailable")}</p>
        <Button label={t("retry")} size="sm" onClick={() => void query.refetch()} />
      </div>
    );
  if (!query.data || query.isFetching)
    return <p className="text-ax-text-secondary text-sm">{t("loading")}</p>;
  return (
    <div className="flex flex-col gap-2">
      <ContextBudget
        maxTokens={model.token_limit}
        variant={variant}
        segments={[
          {
            key: "prompt",
            label: t("prompt"),
            tokens: query.data.prompt_tokens ?? 0,
            className: "bg-chart-1"
          },
          {
            key: "attachments",
            label: t("attachments"),
            tokens: query.data.file_tokens,
            className: "bg-chart-2"
          }
        ]}
      />
      <p className="text-ax-text-secondary phone:sr-only text-sm">{t("assistant_context_scope")}</p>
      {/* A warning leans on the reserve: without it a phone's percentage contradicts it. */}
      <p className={cn("text-ax-text-secondary text-sm", variant === "neutral" && "phone:sr-only")}>
        {t("assistant_context_reserve", { tokens: format.number(reserve) })}
      </p>
      {variant !== "neutral" && (
        <p className={variant === "error" ? "text-destructive text-sm" : "text-warning text-sm"}>
          {t(
            variant === "error" ? "config_attachment_meter_over_budget" : "assistant_context_near"
          )}
        </p>
      )}
    </div>
  );
}
