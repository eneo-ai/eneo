"use client";

import { Brain, ChevronsUpDown, Eye, Lock, Wrench } from "lucide-react";
import { useLocale, useTranslations } from "next-intl";
import { useMemo, useState } from "react";
import { Badge } from "@/components/ui/badge";
import {
  Command,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList
} from "@/components/ui/command";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import type { Schema } from "@/lib/api/models";
import { cn } from "@/lib/utils";
import { formatCostPerMillionTokens } from "@/features/ai-models/format-model-stats";
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

/** The rich detail panel: description, context window, prices, capabilities. */
export function ModelDetails({
  model,
  showPricing
}: {
  model: CompletionModel;
  showPricing: boolean;
}) {
  const t = useTranslations();
  const locale = useLocale();

  const unknown = t("model_cost_unknown");
  const inputPrice = formatCostPerMillionTokens(model.input_cost_per_token) ?? unknown;
  const outputPrice = formatCostPerMillionTokens(model.output_cost_per_token) ?? unknown;
  const contextWindow = t("model_selector_context_value", {
    tokens: new Intl.NumberFormat(locale === "sv" ? "sv-SE" : "en-US").format(
      model.max_input_tokens ?? 0
    )
  });
  const description = model.description?.trim() || t("model_selector_no_description");
  const hasCapabilities = model.vision || model.reasoning || model.supports_tool_calling;

  return (
    <div
      className="flex flex-col"
      aria-label={`${t("model_info_for")} ${model.nickname ?? model.name}`}
    >
      <div className="flex items-center gap-2.5">
        <ProviderLogo provider={model.org ?? model.provider_type} className="size-5" />
        <div className="min-w-0">
          <h3 className="truncate text-sm font-semibold">{model.nickname ?? model.name}</h3>
          <p className="text-muted-foreground truncate text-xs">
            {model.org ?? model.provider_name ?? model.provider_type ?? ""}
          </p>
        </div>
      </div>

      <p className="text-muted-foreground mt-3 text-[13px] leading-5">{description}</p>

      <dl className="mt-3 divide-y text-xs">
        <div className="flex items-center justify-between gap-4 py-2.5">
          <dt className="text-muted-foreground">{t("model_context_label")}</dt>
          <dd className="text-right text-[13px] font-medium tabular-nums">{contextWindow}</dd>
        </div>
        {showPricing && (
          <>
            <div className="flex items-center justify-between gap-4 py-2.5">
              <dt className="text-muted-foreground">{t("model_selector_input_price")}</dt>
              <dd className="text-right text-[13px] font-medium tabular-nums">
                {inputPrice}
                {inputPrice !== unknown && (
                  <span className="text-muted-foreground font-normal">
                    {" / "}
                    {t("model_selector_million_tokens")}
                  </span>
                )}
              </dd>
            </div>
            <div className="flex items-center justify-between gap-4 py-2.5">
              <dt className="text-muted-foreground">{t("model_selector_output_price")}</dt>
              <dd className="text-right text-[13px] font-medium tabular-nums">
                {outputPrice}
                {outputPrice !== unknown && (
                  <span className="text-muted-foreground font-normal">
                    {" / "}
                    {t("model_selector_million_tokens")}
                  </span>
                )}
              </dd>
            </div>
          </>
        )}
      </dl>

      {hasCapabilities && (
        <div className="mt-3">
          <p className="text-muted-foreground mb-2 text-[10px] font-semibold tracking-wider uppercase">
            {t("model_detail_capabilities")}
          </p>
          <div className="flex flex-wrap gap-1.5">
            {model.vision && (
              <Badge variant="outline" className="bg-muted/40 h-6 gap-1 border-0 px-2 text-[11px]">
                <Eye aria-hidden="true" className="size-3" />
                {t("model_label_vision")}
              </Badge>
            )}
            {model.reasoning && (
              <Badge variant="outline" className="bg-muted/40 h-6 gap-1 border-0 px-2 text-[11px]">
                <Brain aria-hidden="true" className="size-3" />
                {t("model_label_reasoning")}
              </Badge>
            )}
            {model.supports_tool_calling && (
              <Badge variant="outline" className="bg-muted/40 h-6 gap-1 border-0 px-2 text-[11px]">
                <Wrench aria-hidden="true" className="size-3" />
                {t("model_label_tool_calling")}
              </Badge>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

type ModelSelectorProps = {
  id?: string;
  models: CompletionModel[];
  selectedId: string | null | undefined;
  onSelect: (id: string) => void;
  /** When the governance policy pins a single model, render a locked label. */
  locked?: ModelRef | null;
  disabled?: boolean;
  size?: "sm" | "default";
  className?: string;
  /** When false, input/output prices are hidden (org-controlled). Defaults to true. */
  showPricing?: boolean;
};

/**
 * AI-Elements model picker: a vendor-grouped, searchable command palette with
 * provider logos and a live detail panel (description, context window, input/
 * output price per 1M tokens, capability badges). Ported from the Svelte
 * `ai-elements/model-selector` + `ChatModelSelect`/`ChatModelDetails`.
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
  const [open, setOpen] = useState(false);
  const [highlightedId, setHighlightedId] = useState<string>("");

  const sorted = useMemo(() => sortModels(models), [models]);
  const groups = useMemo(() => {
    const map = new Map<string, CompletionModel[]>();
    for (const model of sorted) {
      const label = vendorLabel(model, t("model_group_other"));
      const bucket = map.get(label);
      if (bucket) bucket.push(model);
      else map.set(label, [model]);
    }
    return Array.from(map.entries()).sort((a, b) => a[0].localeCompare(b[0]));
  }, [sorted, t]);

  const selectedModel = sorted.find((model) => model.id === selectedId) ?? null;
  const previewModel =
    sorted.find((model) => model.id === highlightedId) ?? selectedModel ?? sorted[0] ?? null;

  const triggerClasses = cn(
    "flex items-center gap-2 rounded-lg border px-2.5 text-sm font-medium transition-colors",
    "hover:bg-accent disabled:pointer-events-none disabled:opacity-50",
    size === "sm" ? "h-8" : "h-9",
    className
  );

  if (locked) {
    return (
      <div
        className="text-muted-foreground flex items-center gap-1.5 rounded-lg px-2.5 py-1.5 text-sm"
        title={t("governance_locked_by_admin")}
      >
        <Lock aria-hidden="true" className="size-3.5" />
        <span className="truncate">{locked.nickname ?? locked.name}</span>
      </div>
    );
  }

  return (
    <Popover
      open={open}
      onOpenChange={(next) => {
        setOpen(next);
        if (!next) setHighlightedId("");
      }}
    >
      <PopoverTrigger
        id={id}
        disabled={disabled}
        className={triggerClasses}
        aria-label={t("completion_model")}
      >
        {selectedModel && (
          <ProviderLogo provider={selectedModel.org ?? selectedModel.provider_type} />
        )}
        <span className="max-w-48 truncate">
          {selectedModel?.nickname ?? selectedModel?.name ?? t("select_a_model")}
        </span>
        <ChevronsUpDown aria-hidden="true" className="text-muted-foreground size-3.5 shrink-0" />
      </PopoverTrigger>
      <PopoverContent align="end" className="w-[22rem] p-0 sm:w-[40rem]">
        <div className="flex">
          <Command
            value={highlightedId}
            onValueChange={setHighlightedId}
            className="flex-1 border-r"
          >
            <CommandInput placeholder={t("search_models")} />
            <CommandList className="max-h-[22rem]">
              <CommandEmpty>{t("no_models_found")}</CommandEmpty>
              {groups.map(([label, groupModels]) => (
                <CommandGroup key={label} heading={label}>
                  {groupModels.map((model) => (
                    <CommandItem
                      key={model.id}
                      value={model.id}
                      keywords={[model.nickname ?? "", model.name, model.org ?? ""]}
                      onSelect={() => {
                        if (model.id !== selectedId) onSelect(model.id);
                        setOpen(false);
                      }}
                      className="gap-2"
                    >
                      <ProviderLogo provider={model.org ?? model.provider_type} />
                      <span className="flex-1 truncate">{model.nickname ?? model.name}</span>
                      <span className="flex items-center gap-1">
                        {model.vision && (
                          <Eye aria-hidden="true" className="text-muted-foreground size-3.5" />
                        )}
                        {model.reasoning && (
                          <Brain aria-hidden="true" className="text-muted-foreground size-3.5" />
                        )}
                        {model.supports_tool_calling && (
                          <Wrench aria-hidden="true" className="text-muted-foreground size-3.5" />
                        )}
                        {model.id === selectedId && (
                          <span className="bg-primary ml-1 size-1.5 rounded-full" />
                        )}
                      </span>
                    </CommandItem>
                  ))}
                </CommandGroup>
              ))}
            </CommandList>
          </Command>
          {previewModel && (
            <aside className="hidden w-72 overflow-y-auto p-4 sm:block">
              <ModelDetails model={previewModel} showPricing={showPricing} />
            </aside>
          )}
        </div>
      </PopoverContent>
    </Popover>
  );
}
