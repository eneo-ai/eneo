"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, Brain, Eye, Plus, RefreshCw, Search, Wrench } from "lucide-react";
import { useTranslations } from "next-intl";
import { useMemo, useState } from "react";
import { toast } from "sonner";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { DialogFooter } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue
} from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { formatCostPerMillionTokens, formatTokens } from "@/features/ai-models/format-model-stats";
import { securityClassificationsQueryOptions } from "@/features/admin/security-classifications/security-classifications";
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
import { providerCapabilitiesQueryOptions } from "./model-providers";
import { createTenantModel, MODELS_KEY, type ModelKind, validateProviderModel } from "./models";

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
  supportedModes,
  onModeChange,
  onCreated,
  onBack
}: {
  providerId: string;
  providerType: string;
  mode?: ModelKind;
  supportedModes?: ModelKind[];
  onModeChange?: (mode: ModelKind) => void;
  onCreated: () => void;
  onBack: () => void;
}) {
  const t = useTranslations();
  const queryClient = useQueryClient();

  const capsQuery = useQuery(providerCapabilitiesQueryOptions(browserApi));
  const securityQuery = useQuery(securityClassificationsQueryOptions(browserApi));
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
  const [classificationId, setClassificationId] = useState("__none__");
  const [validating, setValidating] = useState(false);
  const [createAnyway, setCreateAnyway] = useState(false);
  const [validationFailures, setValidationFailures] = useState<
    { model: string; message: string }[]
  >([]);

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
    setValidationFailures([]);
    setCreateAnyway(false);
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
    setValidationFailures([]);
    setCreateAnyway(false);
  }

  const selectedModels = useMemo(() => [...selected.values()], [selected]);
  const invalidTokenModels =
    mode === "completion"
      ? selectedModels.filter(
          (model) => (model.max_input_tokens ?? 0) <= 0 || (model.max_output_tokens ?? 0) <= 0
        )
      : [];
  const selectedClassification = classificationId === "__none__" ? null : { id: classificationId };

  async function validateSelectedModels(models: CatalogModel[]) {
    const results = await Promise.all(
      models.map(async (model) => {
        const result = (await validateProviderModel(browserApi, providerId, {
          model_name: model.name,
          model_type: mode
        })) as Record<string, unknown>;
        if (result.success === true) return null;
        return {
          model: model.display_name ?? model.name,
          message:
            typeof result.error === "string"
              ? result.error
              : typeof result.message === "string"
                ? result.message
                : t("model_validation_failed")
        };
      })
    );
    return results.filter((result): result is { model: string; message: string } =>
      Boolean(result)
    );
  }

  const create = useMutation({
    mutationFn: async () => {
      const models = selectedModels;
      const results = await Promise.allSettled(
        models.map((model) => {
          const displayName = model.display_name?.trim() || model.name;
          if (mode === "embedding") {
            return createTenantModel(browserApi, "embedding", {
              provider_id: providerId,
              name: model.name,
              display_name: displayName,
              family: providerType,
              dimensions: model.output_vector_size ?? null,
              max_input: model.max_input_tokens ?? null,
              hosting: "swe",
              input_cost_per_token: model.input_cost_per_token ?? null,
              output_cost_per_token: model.output_cost_per_token ?? null,
              security_classification: selectedClassification
            });
          }
          if (mode === "transcription") {
            return createTenantModel(browserApi, "transcription", {
              provider_id: providerId,
              name: model.name,
              display_name: displayName,
              family: providerType,
              hosting: "swe",
              cost_per_minute: model.cost_per_minute ?? null,
              security_classification: selectedClassification
            });
          }
          return createTenantModel(browserApi, "completion", {
            provider_id: providerId,
            name: model.name,
            display_name: displayName,
            max_input_tokens: model.max_input_tokens ?? 0,
            max_output_tokens: model.max_output_tokens ?? 0,
            vision: model.supports_vision,
            reasoning: model.supports_reasoning,
            supports_tool_calling: model.supports_function_calling,
            hosting: "swe",
            family: providerType,
            input_cost_per_token: model.input_cost_per_token ?? null,
            output_cost_per_token: model.output_cost_per_token ?? null,
            security_classification: selectedClassification
          });
        })
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
      setValidationFailures([]);
      setCreateAnyway(false);
      if (failed === 0) toast.success(t("models_added_count", { count: total }));
      else toast.warning(t("models_added_partial", { added: total - failed, total }));
      onCreated();
    },
    onError: (error) => toastApiError(error, t)
  });

  const canList = !NO_SUGGESTIONS_PROVIDERS.has(providerType);
  const canCreate =
    selected.size > 0 && invalidTokenModels.length === 0 && !create.isPending && !validating;
  const modes = supportedModes?.length ? supportedModes : [mode];

  async function handleCreate() {
    if (!canCreate) return;
    if (!createAnyway) {
      setValidating(true);
      try {
        const failures = await validateSelectedModels(selectedModels);
        if (failures.length > 0) {
          setValidationFailures(failures);
          setValidating(false);
          return;
        }
      } catch (error) {
        setValidating(false);
        toastApiError(error, t);
        return;
      }
      setValidating(false);
    }
    create.mutate();
  }

  return (
    <div className="flex flex-col gap-4">
      {modes.length > 1 && onModeChange && (
        <div className="flex flex-col gap-1.5">
          <Label htmlFor="catalog-model-kind">{t("model_type")}</Label>
          <Select
            value={mode}
            onValueChange={(value) => {
              onModeChange(value as ModelKind);
              setSelected(new Map());
              setValidationFailures([]);
              setCreateAnyway(false);
            }}
          >
            <SelectTrigger id="catalog-model-kind" className="w-full">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {modes.map((supportedMode) => (
                <SelectItem key={supportedMode} value={supportedMode}>
                  {t(`${supportedMode}_models`)}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
      )}

      {securityQuery.data?.security_enabled && (
        <div className="flex flex-col gap-1.5">
          <Label htmlFor="catalog-security-classification">{t("security_classification")}</Label>
          <Select value={classificationId} onValueChange={setClassificationId}>
            <SelectTrigger id="catalog-security-classification" className="w-full">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="__none__">{t("none")}</SelectItem>
              {securityQuery.data.security_classifications.map((classification) => (
                <SelectItem key={classification.id} value={classification.id}>
                  {classification.name}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
      )}

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

      {invalidTokenModels.length > 0 && (
        <div className="border-warning/30 bg-warning/10 text-warning flex items-start gap-2 rounded-md border px-3 py-2 text-sm">
          <AlertTriangle className="mt-0.5 size-4 shrink-0" aria-hidden="true" />
          <span>
            {t("model_catalog_token_limits_missing", {
              models: invalidTokenModels.map((model) => model.display_name ?? model.name).join(", ")
            })}
          </span>
        </div>
      )}

      {validationFailures.length > 0 && (
        <div className="border-warning/30 bg-warning/10 flex flex-col gap-2 rounded-md border px-3 py-2 text-sm">
          <div className="text-warning flex items-center gap-2 font-medium">
            <AlertTriangle className="size-4" aria-hidden="true" />
            {t("model_validation_warning_title")}
          </div>
          <ul className="text-muted-foreground flex flex-col gap-1">
            {validationFailures.map((failure) => (
              <li key={failure.model}>
                <Badge variant="outline" className="mr-2">
                  {failure.model}
                </Badge>
                {failure.message}
              </li>
            ))}
          </ul>
          <label className="flex items-center gap-2 text-sm">
            <Checkbox
              checked={createAnyway}
              onCheckedChange={(checked) => setCreateAnyway(checked === true)}
            />
            {t("model_validation_create_anyway_ack")}
          </label>
        </div>
      )}

      <DialogFooter>
        <Button type="button" variant="outline" onClick={onBack}>
          {t("back")}
        </Button>
        <Button
          type="button"
          disabled={!canCreate || (validationFailures.length > 0 && !createAnyway)}
          onClick={() => void handleCreate()}
        >
          {create.isPending
            ? t("saving")
            : validating
              ? t("validating_models")
              : validationFailures.length > 0
                ? t("create_anyway")
                : t("add_n_models", { count: selected.size })}
        </Button>
      </DialogFooter>
    </div>
  );
}
