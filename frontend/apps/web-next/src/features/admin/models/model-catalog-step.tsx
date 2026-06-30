"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Brain, Eye, Plus, RefreshCw, Search, Wrench } from "lucide-react";
import { useTranslations } from "next-intl";
import { useMemo, useState } from "react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { DialogFooter } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { formatCostPerMillionTokens, formatTokens } from "@/features/ai-models/format-model-stats";
import { browserApi } from "@/lib/api/browser";
import { toastApiError } from "@/lib/api/toast";
import { cn } from "@/lib/utils";
import {
  type CatalogModel,
  getModelDefaults,
  listProviderModels,
  NO_SUGGESTIONS_PROVIDERS,
  staticCatalogModels
} from "./model-catalog";
import { createCompletionModel, providerCapabilitiesQueryOptions } from "./model-providers";
import { MODELS_KEY, type ModelKind } from "./models";

function CapabilityIcons({ model }: { model: CatalogModel }) {
  const t = useTranslations();
  const items: { show: boolean; icon: typeof Eye; label: string }[] = [
    { show: model.supports_vision, icon: Eye, label: t("capability_vision") },
    { show: model.supports_function_calling, icon: Wrench, label: t("model_label_tool_calling") },
    { show: model.supports_reasoning, icon: Brain, label: t("reasoning") }
  ];
  return (
    <span className="flex items-center gap-1.5">
      {items
        .filter((item) => item.show)
        .map(({ icon: Icon, label }) => (
          <Tooltip key={label}>
            <TooltipTrigger asChild>
              <span className="text-muted-foreground inline-flex">
                <Icon className="size-4" aria-label={label} />
              </span>
            </TooltipTrigger>
            <TooltipContent>{label}</TooltipContent>
          </Tooltip>
        ))}
    </span>
  );
}

/**
 * Restores the Svelte wizard's "auto-fetch models" step. Pulls the provider's
 * live catalog (`/models`), falling back to the static LiteLLM catalog, and
 * lets the admin multi-select pre-filled models (capabilities + indicative
 * pricing) plus add unlisted ids by hand. All picks are created in one batch.
 */
export function ModelCatalogStep({
  providerId,
  providerType,
  mode = "completion",
  onCreated,
  onBack
}: {
  providerId: string;
  providerType: string;
  mode?: ModelKind;
  onCreated: () => void;
  onBack: () => void;
}) {
  const t = useTranslations();
  const queryClient = useQueryClient();

  const capsQuery = useQuery(providerCapabilitiesQueryOptions(browserApi));
  const liveQuery = useQuery({
    queryKey: ["provider-models", providerId, mode],
    queryFn: () => listProviderModels(browserApi, providerId, mode),
    staleTime: 60_000
  });

  const staticModels = useMemo(
    () => staticCatalogModels(capsQuery.data, providerType, mode),
    [capsQuery.data, providerType, mode]
  );
  const liveModels = liveQuery.data?.models ?? [];
  const catalog = liveModels.length > 0 ? liveModels : staticModels;
  const usedFallback = liveModels.length === 0 && Boolean(liveQuery.data?.error);
  const loading = liveQuery.isLoading || capsQuery.isLoading;

  const [selected, setSelected] = useState<Map<string, CatalogModel>>(new Map());
  const [search, setSearch] = useState("");
  const [manualName, setManualName] = useState("");
  const [manualBusy, setManualBusy] = useState(false);

  const filtered = useMemo(() => {
    const query = search.trim().toLowerCase();
    if (!query) return catalog;
    return catalog.filter((model) =>
      `${model.name} ${model.display_name ?? ""}`.toLowerCase().includes(query)
    );
  }, [catalog, search]);

  function toggle(model: CatalogModel) {
    setSelected((prev) => {
      const next = new Map(prev);
      if (next.has(model.name)) next.delete(model.name);
      else next.set(model.name, model);
      return next;
    });
  }

  async function addManual() {
    const name = manualName.trim();
    if (!name) return;
    if (selected.has(name) || catalog.some((model) => model.name === name)) {
      setManualName("");
      return;
    }
    setManualBusy(true);
    const defaults = await getModelDefaults(browserApi, name, providerType);
    setManualBusy(false);
    const model: CatalogModel = defaults ?? {
      name,
      supports_vision: false,
      supports_function_calling: false,
      supports_reasoning: false
    };
    setSelected((prev) => new Map(prev).set(name, { ...model, name }));
    setManualName("");
  }

  const create = useMutation({
    mutationFn: async () => {
      const models = [...selected.values()];
      const results = await Promise.allSettled(
        models.map((model) =>
          createCompletionModel(browserApi, {
            provider_id: providerId,
            name: model.name,
            display_name: model.display_name?.trim() || model.name,
            max_input_tokens: model.max_input_tokens ?? 0,
            max_output_tokens: model.max_output_tokens ?? 0,
            vision: model.supports_vision,
            reasoning: model.supports_reasoning,
            supports_tool_calling: model.supports_function_calling,
            family: providerType,
            input_cost_per_token: model.input_cost_per_token ?? null,
            output_cost_per_token: model.output_cost_per_token ?? null
          })
        )
      );
      const failures = results.filter((result) => result.status === "rejected");
      // All failed: surface the real error (e.g. "model already exists") and
      // keep the dialog open by throwing so onError runs.
      if (models.length > 0 && failures.length === models.length) {
        throw (failures[0] as PromiseRejectedResult).reason;
      }
      return { total: models.length, failed: failures.length };
    },
    onSuccess: ({ total, failed }) => {
      void queryClient.invalidateQueries({ queryKey: MODELS_KEY });
      if (failed === 0) toast.success(t("models_added_count", { count: total }));
      else toast.warning(t("models_added_partial", { added: total - failed, total }));
      onCreated();
    },
    onError: (error) => toastApiError(error, t)
  });

  const canList = !NO_SUGGESTIONS_PROVIDERS.has(providerType);

  return (
    <div className="flex flex-col gap-4">
      {canList && (
        <>
          <div className="flex items-center gap-2">
            <div className="relative flex-1">
              <Search
                className="text-muted-foreground absolute top-1/2 left-2.5 size-4 -translate-y-1/2"
                aria-hidden="true"
              />
              <Input
                className="pl-8"
                placeholder={t("filter_catalog")}
                value={search}
                onChange={(event) => setSearch(event.target.value)}
                aria-label={t("filter_catalog")}
              />
            </div>
            <Button
              type="button"
              variant="outline"
              size="sm"
              onClick={() => liveQuery.refetch()}
              disabled={liveQuery.isFetching}
            >
              <RefreshCw className={cn("size-4", liveQuery.isFetching && "animate-spin")} />
              {t("refetch")}
            </Button>
          </div>

          <p className="text-muted-foreground text-xs" aria-live="polite">
            {loading ? t("loading") : t("models_found_count", { count: catalog.length })}
            {usedFallback ? ` · ${t("provider_models_fallback_notice")}` : ""}
          </p>

          {loading ? (
            <div className="flex flex-col gap-2">
              <Skeleton className="h-12 w-full" />
              <Skeleton className="h-12 w-full" />
              <Skeleton className="h-12 w-full" />
            </div>
          ) : (
            <div className="max-h-72 overflow-y-auto rounded-lg border">
              {filtered.length === 0 ? (
                <p className="text-muted-foreground p-4 text-sm">{t("no_models_found")}</p>
              ) : (
                filtered.map((model) => {
                  const isSelected = selected.has(model.name);
                  const price = formatCostPerMillionTokens(model.input_cost_per_token);
                  return (
                    <label
                      key={model.name}
                      className={cn(
                        "flex cursor-pointer items-center gap-3 border-b px-3 py-2.5 last:border-b-0",
                        isSelected ? "bg-accent/50" : "hover:bg-muted/50"
                      )}
                    >
                      <Checkbox
                        checked={isSelected}
                        onCheckedChange={() => toggle(model)}
                        aria-label={model.display_name ?? model.name}
                      />
                      <span className="flex min-w-0 flex-1 flex-col">
                        <span className="truncate text-sm font-medium">
                          {model.display_name ?? model.name}
                        </span>
                        <span className="text-muted-foreground truncate font-mono text-xs">
                          {model.name}
                          {model.max_input_tokens
                            ? ` · ${formatTokens(model.max_input_tokens)}`
                            : ""}
                        </span>
                      </span>
                      <CapabilityIcons model={model} />
                      {price && (
                        <span className="text-muted-foreground shrink-0 text-xs tabular-nums">
                          {t("price_per_million", { price })}
                        </span>
                      )}
                    </label>
                  );
                })
              )}
            </div>
          )}
        </>
      )}

      <div className="flex items-end gap-2">
        <div className="flex flex-1 flex-col gap-1.5">
          <label htmlFor="catalog-manual" className="text-muted-foreground text-xs">
            {canList ? t("model_not_listed") : t("enter_model_id")}
          </label>
          <Input
            id="catalog-manual"
            placeholder={t("model_identifier")}
            value={manualName}
            autoComplete="off"
            onChange={(event) => setManualName(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Enter") {
                event.preventDefault();
                void addManual();
              }
            }}
          />
        </div>
        <Button
          type="button"
          variant="outline"
          onClick={() => void addManual()}
          disabled={!manualName.trim() || manualBusy}
        >
          <Plus className="size-4" />
          {t("add")}
        </Button>
      </div>

      {selected.size > 0 && (
        <p className="text-muted-foreground text-xs" aria-live="polite">
          {t("models_selected_count", { count: selected.size })}
        </p>
      )}

      <DialogFooter>
        <Button type="button" variant="outline" onClick={onBack}>
          {t("back")}
        </Button>
        <Button
          type="button"
          disabled={selected.size === 0 || create.isPending}
          onClick={() => create.mutate()}
        >
          {create.isPending ? t("saving") : t("add_n_models", { count: selected.size })}
        </Button>
      </DialogFooter>
    </div>
  );
}
