"use client";

import { Banner } from "@astryxdesign/core/Banner";
import { Button } from "@astryxdesign/core/Button";
import { CheckboxInput } from "@astryxdesign/core/CheckboxInput";
import { CheckboxList, CheckboxListItem } from "@astryxdesign/core/CheckboxList";
import { useAnnounce } from "@astryxdesign/core/hooks";
import { NumberInput } from "@astryxdesign/core/NumberInput";
import { Selector } from "@astryxdesign/core/Selector";
import { Text } from "@astryxdesign/core/Text";
import { TextInput } from "@/components/astryx/text-input";
import { Token } from "@astryxdesign/core/Token";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Plus, RefreshCw, Search } from "lucide-react";
import { useTranslations } from "next-intl";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { flushSync } from "react-dom";
import { LoadingState } from "@/components/composites/loading-state";
import { formatCostPerMillionTokens, formatTokens } from "@/features/ai-models/format-model-stats";
import { securityClassificationsQueryOptions } from "@/features/admin/security-classifications/security-classifications";
import { browserApi } from "@/lib/api/browser";
import { toastApiError } from "@/lib/api/toast";
import { toast } from "@/lib/toast";
import {
  type CatalogModel,
  getModelDefaults,
  listProviderModels,
  NO_SUGGESTIONS_PROVIDERS,
  staticCatalogModels
} from "./model-catalog";
import { providerCapabilitiesQueryOptions } from "./model-providers";
import { useModelTypeLabel } from "./model-type-label";
import {
  type AdminModel,
  adminModelsQueryOptions,
  createTenantModel,
  MODELS_KEY,
  type ModelKind,
  type ModelsPresentation,
  validateProviderModel
} from "./models";
import { useFieldFocus } from "./provider-form-fields";

const NO_CLASSIFICATION = "__none__";

/** Where the tenant's models of each type are listed. */
const MODEL_LISTS = {
  completion: "completion_models",
  embedding: "embedding_models",
  transcription: "transcription_models"
} as const satisfies Record<ModelKind, keyof ModelsPresentation>;

type ExistingModel = Pick<AdminModel, "name" | "nickname" | "provider_id" | "is_deprecated">;

/** A model the catalog knows nothing about. */
const NO_CAPABILITIES = {
  supports_vision: false,
  supports_function_calling: false,
  supports_reasoning: false
};

/** Vision, tools and reasoning in words, as the model table shows them. */
function capabilityLabels(t: ReturnType<typeof useTranslations>, model: CatalogModel): string[] {
  return [
    model.supports_vision ? t("admin_models_capability_vision") : null,
    model.supports_function_calling ? t("model_label_tool_calling") : null,
    model.supports_reasoning ? t("model_label_reasoning") : null
  ].filter((label): label is string => label !== null);
}

/** The display name a pick is created with. */
function createdName(model: CatalogModel): string {
  return model.display_name?.trim() || model.name;
}

/** A completion model needs both token limits before it can be created. */
function missingTokenLimits(model: CatalogModel, mode: ModelKind): boolean {
  return (
    mode === "completion" && (!(model.max_input_tokens ?? 0) || !(model.max_output_tokens ?? 0))
  );
}

/**
 * The wizard's model step: the provider's live model list (`/models`), else
 * the static LiteLLM catalog, to pick several from, plus models added by id.
 * Picks the catalog knows no token limits for ask for them. All picks are
 * validated with the provider and created in one batch.
 *
 * `frame` puts the fields and the step's buttons into the wizard's dialog
 * layout, so the buttons stay in view while the list scrolls.
 */
export function ModelCatalogStep({
  providerId,
  providerType,
  mode = "completion",
  supportedModes,
  onModeChange,
  onCreated,
  onBack,
  frame
}: {
  providerId: string;
  providerType: string;
  mode?: ModelKind;
  supportedModes?: ModelKind[];
  onModeChange?: (mode: ModelKind) => void;
  onCreated: () => void;
  onBack: () => void;
  frame: (content: React.ReactNode, footer: React.ReactNode) => React.ReactNode;
}) {
  const t = useTranslations();
  const typeLabel = useModelTypeLabel();
  const queryClient = useQueryClient();
  const announce = useAnnounce();
  const focus = useFieldFocus();
  const acknowledgeRef = useRef<HTMLInputElement>(null);

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
  // The provider's models of this type: picking one again would be refused
  // (a display name is unique per provider, 9017), so they are marked instead.
  const modelsQuery = useQuery(adminModelsQueryOptions(browserApi));
  const providerModels = useMemo(() => {
    const models: ExistingModel[] = modelsQuery.data?.[MODEL_LISTS[mode]] ?? [];
    return models.filter((model) => model.provider_id === providerId && !model.is_deprecated);
  }, [modelsQuery.data, mode, providerId]);
  /** The provider has this model already: the same id, or the name it would get. */
  const isAdded = useCallback(
    (model: CatalogModel) =>
      providerModels.some(
        (existing) =>
          existing.name === model.name ||
          existing.nickname?.toLowerCase() === createdName(model).toLowerCase()
      ),
    [providerModels]
  );

  const liveModels = liveQuery.data?.models ?? [];
  const catalog = liveModels.length > 0 ? liveModels : staticModels;
  const usedFallback = liveModels.length === 0 && Boolean(liveQuery.data?.error);
  const loading = liveQuery.isLoading || capsQuery.isLoading || modelsQuery.isLoading;

  const [selected, setSelected] = useState<Map<string, CatalogModel>>(new Map());
  const [search, setSearch] = useState("");
  const [manualName, setManualName] = useState("");
  const [manualBusy, setManualBusy] = useState(false);
  /** An id typed in that the provider has already. */
  const [manualTaken, setManualTaken] = useState<string | null>(null);
  const [classificationId, setClassificationId] = useState(NO_CLASSIFICATION);
  const [validating, setValidating] = useState(false);
  const [createAnyway, setCreateAnyway] = useState(false);
  const [submitted, setSubmitted] = useState(false);
  const [validationFailures, setValidationFailures] = useState<
    { model: string; message: string }[]
  >([]);

  const countText = `${t("models_found_count", { count: catalog.length })}${
    usedFallback ? ` · ${t("provider_models_fallback_notice")}` : ""
  }`;
  // How many models the list offers, once it has loaded (WCAG 4.1.3).
  const wasLoading = useRef(loading);
  useEffect(() => {
    if (wasLoading.current && !loading) announce(countText);
    wasLoading.current = loading;
  }, [loading, countText, announce]);

  // Picks added by id are not in the catalog; they head the list so they can
  // be seen and unticked like the others.
  const listed = useMemo(() => {
    const query = search.trim().toLowerCase();
    const added = [...selected.values()].filter(
      (model) => !catalog.some((item) => item.name === model.name)
    );
    return [...added, ...catalog].filter(
      (model) => !query || `${model.name} ${model.display_name ?? ""}`.toLowerCase().includes(query)
    );
  }, [catalog, search, selected]);

  function resetOutcome() {
    setValidationFailures([]);
    setCreateAnyway(false);
  }

  /** The list reports the ticked models it shows; picks it hides are kept. */
  function selectListed(names: string[]) {
    setSelected((previous) => {
      const shown = new Set(listed.map((model) => model.name));
      const next = new Map([...previous].filter(([name]) => !shown.has(name)));
      for (const name of names) {
        const model = previous.get(name) ?? listed.find((item) => item.name === name);
        if (model) next.set(name, model);
      }
      return next;
    });
    resetOutcome();
  }

  function setTokenLimit(
    name: string,
    key: "max_input_tokens" | "max_output_tokens",
    value: number
  ) {
    setSelected((previous) => {
      const model = previous.get(name);
      if (!model) return previous;
      return new Map(previous).set(name, { ...model, [key]: value });
    });
    resetOutcome();
  }

  async function addManual() {
    const name = manualName.trim();
    if (!name || manualBusy) return;
    let model = selected.get(name) ?? catalog.find((item) => item.name === name);
    // Said at the field, which keeps focus.
    if (isAdded(model ?? { ...NO_CAPABILITIES, name })) {
      setManualTaken(name);
      return;
    }
    if (!model) {
      setManualBusy(true);
      const defaults = await getModelDefaults(browserApi, name, providerType);
      setManualBusy(false);
      model = { ...(defaults ?? NO_CAPABILITIES), name };
    }
    const next = new Map(selected).set(name, model);
    setSelected(next);
    setManualName("");
    // Focus stays in the field; the list shows the pick at the top.
    announce(t("models_selected_count", { count: next.size }));
    resetOutcome();
  }

  const selectedModels = useMemo(() => [...selected.values()], [selected]);
  const needsLimits = selectedModels.filter((model) => missingTokenLimits(model, mode));
  const selectedClassification =
    classificationId === NO_CLASSIFICATION ? null : { id: classificationId };

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
          const displayName = createdName(model);
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
      resetOutcome();
      if (failed === 0) toast.success(t("models_added_count", { count: total }));
      else toast.warning(t("models_added_partial", { added: total - failed, total }));
      onCreated();
    },
    onError: (error) => toastApiError(error, t)
  });

  const busy = create.isPending || validating;
  const canList = !NO_SUGGESTIONS_PROVIDERS.has(providerType);
  const modes = supportedModes?.length ? supportedModes : [mode];

  /** Moves focus to the first problem, shown at its field (WCAG 3.3.1). */
  function focusFirstProblem(): boolean {
    if (selected.size === 0) return focus.focus("list") || focus.focus("manual");
    const model = needsLimits[0];
    if (!model) return false;
    return focus.focus(
      `${model.name}:${model.max_input_tokens ? "max_output_tokens" : "max_input_tokens"}`
    );
  }

  async function handleCreate() {
    if (busy) return;
    if (selected.size === 0 || needsLimits.length > 0) {
      flushSync(() => setSubmitted(true));
      focusFirstProblem();
      return;
    }
    if (validationFailures.length > 0 && !createAnyway) {
      acknowledgeRef.current?.focus();
      return;
    }
    if (!createAnyway) {
      setValidating(true);
      try {
        const failures = await validateSelectedModels(selectedModels);
        if (failures.length > 0) {
          flushSync(() => {
            setValidationFailures(failures);
            setValidating(false);
          });
          // The next decision: create anyway, or change the picks.
          acknowledgeRef.current?.focus();
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

  const noSelection = submitted && selected.size === 0;

  const content = (
    <div className="flex flex-col gap-5">
      {modes.length > 1 && onModeChange && (
        <Selector
          label={t("model_type")}
          options={modes.map((value) => ({ value, label: typeLabel(value) }))}
          value={mode}
          onChange={(value) => {
            onModeChange(value as ModelKind);
            setSelected(new Map());
            setSubmitted(false);
            resetOutcome();
          }}
        />
      )}

      {securityQuery.data?.security_enabled && (
        <Selector
          label={t("security_classification")}
          options={[
            { value: NO_CLASSIFICATION, label: t("none") },
            ...securityQuery.data.security_classifications.map((classification) => ({
              value: classification.id,
              label: classification.name
            }))
          ]}
          value={classificationId}
          onChange={setClassificationId}
        />
      )}

      {canList && (
        <div className="flex flex-col gap-3">
          <div className="flex flex-wrap items-end gap-2">
            <div className="min-w-48 flex-1">
              <TextInput
                label={t("filter_catalog")}
                isLabelHidden
                placeholder={t("filter_catalog")}
                startIcon={Search}
                value={search}
                onChange={setSearch}
                hasClear
              />
            </div>
            <Button
              label={t("provider_form_refetch_models")}
              icon={<RefreshCw className="size-4" aria-hidden="true" />}
              // Keeps focus while the list reloads; a second press is ignored.
              isLoading={liveQuery.isFetching}
              isInterruptible
              onClick={() => {
                if (!liveQuery.isFetching) void liveQuery.refetch();
              }}
            >
              {t("refetch")}
            </Button>
          </div>
          {loading ? (
            <LoadingState rows={3} label={t("loading")} />
          ) : (
            <>
              <Text type="supporting">{countText}</Text>
              {listed.length === 0 ? (
                <Text type="supporting">{t("no_models_found")}</Text>
              ) : (
                <CheckboxList
                  ref={focus.ref("list")}
                  label={t("provider_form_catalog_label")}
                  isLabelHidden
                  value={listed.map((model) => model.name).filter((name) => selected.has(name))}
                  onChange={selectListed}
                  density="compact"
                  hasDividers
                  // The options scroll in their own box (focus scrolls them from
                  // the keyboard); the error below stays in view.
                  className="[&_[role=group]]:border-ax-border [&_[role=group]]:rounded-ax-element [&_[role=group]]:max-h-72 [&_[role=group]]:overflow-y-auto [&_[role=group]]:border [&_[role=group]]:px-3 [&_[role=group]]:py-1"
                  status={
                    noSelection
                      ? { type: "error", message: t("provider_form_select_model_required") }
                      : undefined
                  }
                >
                  {listed.map((model) => {
                    const added = isAdded(model);
                    const price = formatCostPerMillionTokens(model.input_cost_per_token);
                    const capabilities = capabilityLabels(t, model);
                    const details = [
                      // In words, not only as the dimmed checkbox (WCAG 1.4.1).
                      added ? t("provider_form_model_added") : null,
                      model.display_name && model.display_name !== model.name ? model.name : null,
                      model.max_input_tokens ? formatTokens(model.max_input_tokens) : null,
                      price ? t("price_per_million", { price }) : null
                    ].filter(Boolean);
                    return (
                      <CheckboxListItem
                        key={model.name}
                        value={model.name}
                        label={model.display_name ?? model.name}
                        isDisabled={added}
                        // Below the name, not beside it: on a phone the name
                        // would be cut off.
                        description={
                          details.length > 0 || capabilities.length > 0 ? (
                            <span className="flex flex-col gap-1">
                              {details.length > 0 ? <span>{details.join(" · ")}</span> : null}
                              {capabilities.length > 0 ? (
                                <span className="flex flex-wrap gap-1">
                                  {capabilities.map((label) => (
                                    <Token key={label} label={label} size="sm" />
                                  ))}
                                </span>
                              ) : null}
                            </span>
                          ) : undefined
                        }
                      />
                    );
                  })}
                </CheckboxList>
              )}
            </>
          )}
        </div>
      )}

      <div className="flex flex-wrap items-end gap-2">
        <div className="min-w-48 flex-1">
          <TextInput
            ref={focus.ref("manual")}
            label={canList ? t("model_not_listed") : t("enter_model_id")}
            placeholder={t("model_identifier")}
            value={manualName}
            onChange={(value) => {
              setManualName(value);
              setManualTaken(null);
            }}
            onEnter={() => void addManual()}
            autoComplete="off"
            status={
              manualTaken
                ? {
                    type: "error",
                    message: t("provider_form_model_added_error", { name: manualTaken })
                  }
                : noSelection && !canList
                  ? { type: "error", message: t("provider_form_select_model_required") }
                  : undefined
            }
          />
        </div>
        <Button
          label={t("provider_form_add_model_id")}
          icon={<Plus className="size-4" aria-hidden="true" />}
          isLoading={manualBusy}
          isInterruptible
          onClick={() => void addManual()}
        >
          {t("add")}
        </Button>
      </div>

      {needsLimits.map((model) => (
        <fieldset key={model.name} className="flex min-w-0 flex-col gap-3">
          <legend className="text-ax-text mb-1 text-sm font-semibold">
            {model.display_name ?? model.name}
          </legend>
          <Text type="supporting">{t("provider_form_token_limits_description")}</Text>
          <div className="grid gap-3 sm:grid-cols-2">
            {(["max_input_tokens", "max_output_tokens"] as const).map((key) => (
              <NumberInput
                key={key}
                ref={focus.ref(`${model.name}:${key}`)}
                label={t(key)}
                value={model[key] ?? null}
                onChange={(value) => setTokenLimit(model.name, key, value)}
                isRequired
                isIntegerOnly
                min={1}
                status={
                  submitted && !(model[key] ?? 0)
                    ? { type: "error", message: t("provider_form_token_limit_required") }
                    : undefined
                }
              />
            ))}
          </div>
        </fieldset>
      ))}

      {selected.size > 0 && (
        <Text type="supporting">{t("models_selected_count", { count: selected.size })}</Text>
      )}

      {validationFailures.length > 0 && (
        <div className="flex flex-col gap-3">
          {/* Mounted by the press on the create button: announced as an alert. */}
          <Banner status="warning" title={t("model_validation_warning_title")} collapsible={false}>
            <ul className="flex flex-col gap-1.5">
              {validationFailures.map((failure) => (
                <li key={failure.model} className="flex flex-wrap items-center gap-2 text-sm">
                  <Token label={failure.model} size="sm" />
                  <span className="text-ax-text-secondary">{failure.message}</span>
                </li>
              ))}
            </ul>
          </Banner>
          <CheckboxInput
            ref={acknowledgeRef}
            label={t("model_validation_create_anyway_ack")}
            value={createAnyway}
            onChange={setCreateAnyway}
          />
        </div>
      )}
    </div>
  );

  const footer = (
    <div className="flex flex-wrap justify-end gap-2">
      <Button label={t("back")} isDisabled={busy} onClick={onBack} />
      <Button
        variant="primary"
        label={
          validationFailures.length > 0
            ? t("create_anyway")
            : t("add_n_models", { count: selected.size })
        }
        // Keeps focus while models are validated and created.
        isLoading={busy}
        isInterruptible
        onClick={() => void handleCreate()}
      />
    </div>
  );

  return frame(content, footer);
}
