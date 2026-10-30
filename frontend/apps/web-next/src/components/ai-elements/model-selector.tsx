"use client";

import { modelDisplayName } from "@/lib/models/model-display-name";
import {
  Selector,
  SelectorOption,
  type SelectorOptionData,
  type SelectorOptionType
} from "@astryxdesign/core/Selector";
import { Lock } from "lucide-react";
import { useTranslations } from "use-intl";
import { useMemo, useState } from "react";
import type { Schema } from "@/lib/api/models";
import { cn } from "@/lib/utils";
import { formatCostPerMillionTokens, formatTokens } from "@/features/ai-models/format-model-stats";
import { sortModels } from "@/features/ai-models/sort-models";
import { ProviderLogo } from "./provider-logo";

type CompletionModel = Schema<"CompletionModelPublic">;

/** Thin reference (e.g. a policy `locked_model`) needs only these fields. */
type ModelRef = {
  id: string;
  name: string;
  nickname?: string | null;
  org?: string | null;
  provider_type?: string | null;
};

type Translate = ReturnType<typeof useTranslations>;

function prettifyProviderType(type: string | null | undefined): string | null {
  if (!type) return null;
  return type
    .split("_")
    .map((word) => word.charAt(0).toUpperCase() + word.slice(1))
    .join(" ");
}

function vendorLabel(model: CompletionModel, fallback: string): string {
  return (
    model.org?.trim() ||
    model.provider_name?.trim() ||
    prettifyProviderType(model.provider_type) ||
    fallback
  );
}

function modelName(model: ModelRef): string {
  return modelDisplayName(model);
}

/**
 * What a row says under the model's name, as text: context window,
 * capabilities and (when the organisation shows them) prices per 1M tokens.
 */
function modelFacts(model: CompletionModel, showPricing: boolean, t: Translate): string {
  const facts: string[] = [];
  if (model.max_input_tokens != null && model.max_input_tokens > 0) {
    facts.push(t("model_context_tokens", { tokens: formatTokens(model.max_input_tokens) }));
  }
  if (model.vision) facts.push(t("model_label_vision"));
  if (model.reasoning) facts.push(t("model_label_reasoning"));
  if (model.supports_tool_calling) facts.push(t("model_label_tool_calling"));
  if (showPricing) {
    const input = formatCostPerMillionTokens(model.input_cost_per_token);
    const output = formatCostPerMillionTokens(model.output_cost_per_token);
    if (input || output) {
      facts.push(t("model_cost_per_million", { input: input ?? "–", output: output ?? "–" }));
    }
  }
  return facts.join(" · ");
}

/**
 * The composer's footer cannot shrink its send actions, so the compact
 * trigger caps the model's name, and below 360 px shows only the provider's
 * logo, to keep the send button inside a 320 px screen. The full name stays
 * in the trigger's accessible name and in the list.
 */
const COMPACT_NAME = "max-w-[min(12rem,30vw)] max-[359px]:hidden";

function ModelValue({ model, compact }: { model: ModelRef; compact: boolean }) {
  return (
    <span className="flex min-w-0 items-center gap-2">
      <ProviderLogo provider={model.org ?? model.provider_type} />
      <span className={cn("truncate", compact && COMPACT_NAME)}>{modelName(model)}</span>
    </span>
  );
}

/** The value of the "follow the default" option; never a model id. */
const DEFAULT_VALUE = "default-model";

/**
 * A first option that follows a default instead of naming a model (the flow
 * chat's "Använd standard"). The default's own model is named in that option
 * and marked in the list.
 */
export type ModelSelectorDefault = {
  /** The option's name. */
  label: string;
  /** The model the default resolves to now, if any. */
  modelId: string | null;
  /** The default is the current choice. */
  isSelected: boolean;
  /** Picks the default; return the save's promise as with `onSelect`. */
  onSelect: () => void | Promise<unknown>;
};

type ModelSelectorProps = {
  /** Id of the trigger, for a `<label htmlFor>` around it (settings rows). */
  id?: string;
  models: CompletionModel[];
  selectedId: string | null | undefined;
  /**
   * Called with a newly chosen model. Return the save's promise to show the
   * new model with a spinner while it saves (the trigger keeps focus); a
   * rejected save falls back to `selectedId`, so report the failure yourself.
   */
  onSelect: (id: string) => void | Promise<unknown>;
  /** A model the governance policy pins: shown read-only, with a lock. */
  locked?: ModelRef | null;
  disabled?: boolean;
  /** `sm`: the borderless trigger for toolbars (the chat composer); default: a form field. */
  size?: "sm" | "default";
  /** Classes for the trigger. */
  className?: string;
  /** When false, input/output prices are hidden (org-controlled). Defaults to true. */
  showPricing?: boolean;
  /** Offer "follow the default" as the first option. */
  defaultChoice?: ModelSelectorDefault;
  /**
   * A form field's own visible label and help text (a settings page); by
   * default the picker is named "Chattmodell" and its label is hidden.
   */
  field?: { label: string; description?: string };
  /** A problem to show at the field (a refused save). */
  status?: { type: "error"; message: string };
};

/**
 * The completion-model picker (Astryx Selector): a search over name and
 * vendor, models grouped by vendor with provider logos, and each row saying
 * its context window, capabilities and prices as text. On phones with touch
 * it opens as a bottom sheet. A model pinned by the governance policy shows
 * as a read-only field with a lock.
 */
export function ModelSelector({
  id,
  models,
  selectedId,
  onSelect,
  locked = null,
  disabled = false,
  size = "default",
  className,
  showPricing = true,
  defaultChoice,
  field,
  status
}: ModelSelectorProps) {
  const t = useTranslations();
  const label = field?.label ?? t("completion_model");
  const compact = size === "sm";

  const [pendingId, setPendingId] = useState<string | null>(null);

  const sorted = useMemo(() => sortModels(models), [models]);
  const byId = useMemo(() => new Map(sorted.map((model) => [model.id, model])), [sorted]);
  const defaultModelId = defaultChoice?.modelId ?? null;
  const defaultModel = defaultModelId ? byId.get(defaultModelId) : undefined;
  const shownId = pendingId ?? (defaultChoice?.isSelected ? DEFAULT_VALUE : selectedId);
  const followsDefault = shownId === DEFAULT_VALUE;
  const selected = followsDefault ? defaultModel : shownId ? byId.get(shownId) : undefined;
  const guidance = (locked ? byId.get(locked.id) : selected)?.description?.trim();
  // The compact composer has no room for help text. Form pickers keep the
  // administrator's advice visible after the list closes.
  const guidanceText =
    !compact && guidance ? <p className="text-ax-text-secondary text-sm">{guidance}</p> : null;
  const options = useMemo<SelectorOptionType[]>(() => {
    const groups = new Map<string, SelectorOptionData[]>();
    for (const model of sorted) {
      const vendor = vendorLabel(model, t("model_group_other"));
      const facts = modelFacts(model, showPricing, t);
      const option: SelectorOptionData = {
        value: model.id,
        // Selector searches its options' labels, and the rows render their
        // own content (renderOption): the label is the search text.
        label: [...new Set([modelName(model), model.name, vendor])].join(" "),
        description:
          model.id === defaultModelId
            ? [t("model_selector_is_default"), facts].filter(Boolean).join(" · ")
            : facts
      };
      const bucket = groups.get(vendor);
      if (bucket) bucket.push(option);
      else groups.set(vendor, [option]);
    }
    const sections: SelectorOptionType[] = Array.from(groups.entries())
      .sort((a, b) => a[0].localeCompare(b[0]))
      .map(([vendor, vendorOptions]) => ({
        type: "section",
        title: vendor,
        options: vendorOptions
      }));
    if (!defaultChoice) return sections;
    const following = defaultModel ? modelName(defaultModel) : undefined;
    return [
      {
        value: DEFAULT_VALUE,
        label: [defaultChoice.label, following].filter(Boolean).join(" "),
        description: following
      },
      ...sections
    ];
  }, [sorted, showPricing, t, defaultModelId, defaultModel, defaultChoice]);

  const shared = {
    id,
    label,
    isLabelHidden: !field,
    description: field?.description,
    variant: compact ? "ghost" : "input",
    // The chat composer's controls are 32 px (md); the settings forms' 36 px (lg).
    size: compact ? "md" : "lg",
    width: compact ? undefined : "100%",
    presentation: "adaptive",
    className
  } as const;

  if (locked) {
    return (
      <>
        <Selector
          {...shared}
          // Read-only keeps the model's name readable (disabled would dim it)
          // and the trigger a focusable combobox whose value is the model.
          isReadOnly
          description={t("governance_locked_by_admin")}
          // One name even when a settings row labels the trigger as well.
          aria-label={label}
          startIcon={Lock}
          options={[{ value: locked.id, label: modelName(locked) }]}
          value={locked.id}
          renderValue={() => (
            <span className={cn("block truncate", compact && COMPACT_NAME)}>
              {modelName(locked)}
            </span>
          )}
        />
        {guidanceText}
      </>
    );
  }

  // A choice that is still saving is the value, in the trigger and in its
  // name. (Selector's `changeAction` would show it in the trigger only.)
  const valueText = followsDefault
    ? defaultModel
      ? t("model_selector_default_value", { model: modelName(defaultModel) })
      : defaultChoice!.label
    : selected
      ? modelName(selected)
      : shownId
        ? t("unsupported_model_selected")
        : t("select_a_model");

  return (
    <>
      <Selector
        {...shared}
        // With a search field the trigger is a plain button that Astryx 0.6.3
        // names by its label alone, so the chosen model would not be read out.
        aria-label={t("legacy_model_selector_trigger", { label, model: valueText })}
        options={options}
        value={followsDefault ? DEFAULT_VALUE : selected?.id}
        onChange={(next) => {
          if (next === shownId) return;
          setPendingId(next);
          const save =
            next === DEFAULT_VALUE && defaultChoice ? defaultChoice.onSelect() : onSelect(next);
          void Promise.resolve(save)
            // The caller reports a failed save; the trigger shows `selectedId` again.
            .catch(() => {})
            .finally(() => setPendingId((current) => (current === next ? null : current)));
        }}
        status={status}
        isLoading={pendingId !== null}
        isDisabled={disabled}
        placeholder={valueText}
        hasSearch
        searchPlaceholder={t("search_models_and_providers")}
        emptyText={t("no_models_found")}
        emptySearchText={t("no_models_found")}
        renderValue={(option) => {
          const model = option.value === DEFAULT_VALUE ? defaultModel : byId.get(option.value);
          if (model) return <ModelValue model={model} compact={compact} />;
          return option.value === DEFAULT_VALUE && defaultChoice ? (
            <span className={cn("block truncate", compact && COMPACT_NAME)}>
              {defaultChoice.label}
            </span>
          ) : null;
        }}
        renderOption={(option) => {
          if (option.value === DEFAULT_VALUE && defaultChoice) {
            return (
              <SelectorOption
                label={<span>{defaultChoice.label}</span>}
                description={option.description ? <span>{option.description}</span> : undefined}
                className="min-w-[min(18rem,calc(100vw_-_4rem))]"
              />
            );
          }
          const model = byId.get(option.value);
          if (!model) return null;
          // Elements, not strings: Item cuts a string label or description to
          // one line with an ellipsis, and these must wrap to stay readable.
          return (
            <SelectorOption
              icon={<ProviderLogo provider={model.org ?? model.provider_type} />}
              label={<span>{modelName(model)}</span>}
              description={option.description ? <span>{option.description}</span> : undefined}
              // A readable width even under a narrow trigger (the popup takes
              // the width of its rows) that still fits a 320 px screen.
              className="min-w-[min(18rem,calc(100vw_-_4rem))]"
            />
          );
        }}
      />
      {guidanceText}
    </>
  );
}
