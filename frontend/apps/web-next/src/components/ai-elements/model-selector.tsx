"use client";

import {
  Selector,
  SelectorOption,
  type SelectorOptionData,
  type SelectorOptionType
} from "@astryxdesign/core/Selector";
import { Lock } from "lucide-react";
import { useTranslations } from "next-intl";
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
  return model.nickname ?? model.name;
}

/**
 * What a row says under the model's name, as text: context window,
 * capabilities and (when the organisation shows them) prices per 1M tokens.
 */
function modelFacts(model: CompletionModel, showPricing: boolean, t: Translate): string {
  const facts: string[] = [];
  if (model.max_input_tokens > 0) {
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
 * trigger caps the model's name (the full name is in the trigger's name and
 * the list) to keep the footer inside a 320 px screen.
 */
const COMPACT_NAME = "max-w-[min(12rem,30vw)]";

function ModelValue({ model, compact }: { model: ModelRef; compact: boolean }) {
  return (
    <span className="flex min-w-0 items-center gap-2">
      <ProviderLogo provider={model.org ?? model.provider_type} />
      <span className={cn("truncate", compact && COMPACT_NAME)}>{modelName(model)}</span>
    </span>
  );
}

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
  showPricing = true
}: ModelSelectorProps) {
  const t = useTranslations();
  const label = t("completion_model");
  const compact = size === "sm";

  const [pendingId, setPendingId] = useState<string | null>(null);

  const sorted = useMemo(() => sortModels(models), [models]);
  const byId = useMemo(() => new Map(sorted.map((model) => [model.id, model])), [sorted]);
  const options = useMemo<SelectorOptionType[]>(() => {
    const groups = new Map<string, SelectorOptionData[]>();
    for (const model of sorted) {
      const vendor = vendorLabel(model, t("model_group_other"));
      const option: SelectorOptionData = {
        value: model.id,
        // Selector searches its options' labels, and the rows render their
        // own content (renderOption): the label is the search text.
        label: [...new Set([modelName(model), model.name, vendor])].join(" "),
        description: modelFacts(model, showPricing, t)
      };
      const bucket = groups.get(vendor);
      if (bucket) bucket.push(option);
      else groups.set(vendor, [option]);
    }
    return Array.from(groups.entries())
      .sort((a, b) => a[0].localeCompare(b[0]))
      .map(([vendor, vendorOptions]) => ({
        type: "section",
        title: vendor,
        options: vendorOptions
      }));
  }, [sorted, showPricing, t]);

  const shared = {
    id,
    label,
    isLabelHidden: true,
    variant: compact ? "ghost" : "input",
    // The chat composer's controls are 32 px (md); the settings forms' 36 px (lg).
    size: compact ? "md" : "lg",
    width: compact ? undefined : "100%",
    presentation: "adaptive",
    className
  } as const;

  if (locked) {
    return (
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
          <span className={cn("block truncate", compact && COMPACT_NAME)}>{modelName(locked)}</span>
        )}
      />
    );
  }

  // A choice that is still saving is the value, in the trigger and in its
  // name. (Selector's `changeAction` would show it in the trigger only.)
  const shownId = pendingId ?? selectedId;
  const selected = shownId ? byId.get(shownId) : undefined;
  const valueText = selected
    ? modelName(selected)
    : shownId
      ? t("unsupported_model_selected")
      : t("select_a_model");

  return (
    <Selector
      {...shared}
      // With a search field the trigger is a plain button that Astryx 0.6.3
      // names by its label alone, so the chosen model would not be read out.
      aria-label={t("legacy_model_selector_trigger", { label, model: valueText })}
      options={options}
      value={selected?.id}
      onChange={(next) => {
        if (next === shownId) return;
        setPendingId(next);
        void Promise.resolve(onSelect(next))
          // The caller reports a failed save; the trigger shows `selectedId` again.
          .catch(() => {})
          .finally(() => setPendingId((current) => (current === next ? null : current)));
      }}
      isLoading={pendingId !== null}
      isDisabled={disabled}
      placeholder={valueText}
      hasSearch
      searchPlaceholder={t("search_models_and_providers")}
      emptyText={t("no_models_found")}
      emptySearchText={t("no_models_found")}
      renderValue={(option) => {
        const model = byId.get(option.value);
        return model ? <ModelValue model={model} compact={compact} /> : null;
      }}
      renderOption={(option) => {
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
  );
}
