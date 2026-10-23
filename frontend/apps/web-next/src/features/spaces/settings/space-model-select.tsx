"use client";

import { Button as AstryxButton } from "@astryxdesign/core/Button";
import { Brain, ChevronDown, ChevronRight, Eye, Wrench } from "lucide-react";
import { useTranslations } from "next-intl";
import { useId, useMemo, useRef, useState } from "react";
import { ProviderLogo } from "@/components/ai-elements/provider-logo";
import { Button } from "@/components/ui/button";
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible";
import { Switch } from "@/components/ui/switch";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import {
  formatCostPerMillionTokens,
  formatCostPerMinute
} from "@/features/ai-models/format-model-stats";
import { cn } from "@/lib/utils";
import { ResourceFilterInput } from "../resource-filter-input";

export type SelectableModel = {
  id: string;
  name: string;
  nickname?: string | null;
  meets_security_classification?: boolean | null;
  org?: string | null;
  provider_type?: string | null;
  vision?: boolean | null;
  reasoning?: boolean | null;
  supports_tool_calling?: boolean | null;
  input_cost_per_token?: string | number | null;
  output_cost_per_token?: string | number | null;
  cost_per_minute?: string | number | null;
};

export type ModelKind = "completion" | "embedding" | "transcription";
export type ModelSelectionChange = (currentIds: string[]) => string[];

const SEARCH_THRESHOLD = 6;

function label(model: SelectableModel): string {
  return model.nickname ?? model.name;
}

function groupName(model: SelectableModel, fallback: string): string {
  const raw = model.org || model.provider_type || fallback;
  return raw.charAt(0).toUpperCase() + raw.slice(1);
}

function costText(model: SelectableModel, kind: ModelKind): string | null {
  if (kind === "transcription") {
    const value = formatCostPerMinute(model.cost_per_minute);
    return value ? `${value}/min` : null;
  }
  const input = formatCostPerMillionTokens(model.input_cost_per_token);
  const output = formatCostPerMillionTokens(model.output_cost_per_token);
  if (!input && !output) return null;
  if (input && output && input !== output) return `${input} / ${output}`;
  return input ?? output ?? null;
}

function CapabilityIcons({ model }: { model: SelectableModel }) {
  const t = useTranslations();
  const items = [
    model.vision ? { Icon: Eye, text: t("model_label_vision") } : null,
    model.reasoning ? { Icon: Brain, text: t("model_label_reasoning") } : null,
    model.supports_tool_calling ? { Icon: Wrench, text: t("model_label_tool_calling") } : null
  ].filter((item): item is { Icon: typeof Eye; text: string } => item !== null);

  if (items.length === 0) return null;

  return (
    <span className="flex items-center gap-1.5">
      {items.map(({ Icon, text }) => (
        <Tooltip key={text}>
          <TooltipTrigger asChild>
            <span className="text-muted-foreground inline-flex">
              <Icon className="size-4" aria-label={text} />
            </span>
          </TooltipTrigger>
          <TooltipContent>{text}</TooltipContent>
        </Tooltip>
      ))}
    </span>
  );
}

/**
 * Space model availability picker. The closed card shows the current selection;
 * opening it reveals the existing per-vendor controls and autosave behaviour.
 */
export function SpaceModelSelect({
  models,
  selectedIds,
  title,
  description,
  kind,
  onChange
}: {
  models: SelectableModel[];
  selectedIds: string[];
  title: string;
  description: string;
  kind: ModelKind;
  onChange: (change: ModelSelectionChange) => void;
}) {
  const t = useTranslations();
  const [isOpen, setIsOpen] = useState(false);
  const [search, setSearch] = useState("");
  const [openOverride, setOpenOverride] = useState<Record<string, boolean>>({});
  const searchRef = useRef<HTMLInputElement>(null);
  const reasonPrefix = useId();

  const selected = useMemo(() => new Set(selectedIds), [selectedIds]);
  const selectedModels = models.filter((model) => selected.has(model.id));
  const selectedPreview = selectedModels.slice(0, 2);
  const moreSelected = selectedIds.length - selectedPreview.length;
  const query = search.trim().toLowerCase();
  const searching = query !== "";
  const otherProvider = t("space_models_other_provider");

  const groups = useMemo(() => {
    const map = new Map<string, SelectableModel[]>();
    for (const model of models) {
      const key = groupName(model, otherProvider);
      const list = map.get(key) ?? [];
      list.push(model);
      map.set(key, list);
    }
    return [...map.entries()].map(([name, list]) => ({ name, models: list }));
  }, [models, otherProvider]);
  const visibleGroups = groups
    .map((group) => ({
      ...group,
      visible:
        !searching || group.name.toLowerCase().includes(query)
          ? group.models
          : group.models.filter(
              (model) =>
                label(model).toLowerCase().includes(query) ||
                (model.provider_type?.toLowerCase().includes(query) ?? false)
            )
    }))
    .filter((group) => group.visible.length > 0);

  function toggleOne(id: string, group: string) {
    // Keep the focused switch mounted when this was the group's last selection.
    setOpenOverride((prev) => ({ ...prev, [group]: true }));
    onChange((current) =>
      current.includes(id) ? current.filter((selectedId) => selectedId !== id) : [...current, id]
    );
  }

  function setWholeGroup(groupModels: SelectableModel[]) {
    const ids = groupModels
      .filter((model) => model.meets_security_classification ?? true)
      .map((model) => model.id);
    onChange((current) => {
      const selected = new Set(current);
      if (ids.every((id) => selected.has(id))) {
        const remove = new Set(ids);
        return current.filter((id) => !remove.has(id));
      }
      ids.forEach((id) => selected.add(id));
      return [...selected];
    });
  }

  return (
    <Collapsible open={isOpen} onOpenChange={setIsOpen} className="border-border rounded-lg border">
      <div className="flex flex-wrap items-start justify-between gap-3 p-4">
        <div className="min-w-0 flex-1">
          <h3 className="text-base font-semibold">{title}</h3>
          <p className="text-muted-foreground mt-1 text-sm">{description}</p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <span className="bg-muted rounded-md px-2 py-1 text-xs font-medium tabular-nums">
            {t("models_selected_count", { count: selectedIds.length })}
          </span>
          {models.length > 0 ? (
            <CollapsibleTrigger asChild>
              <Button
                type="button"
                variant="outline"
                size="sm"
                aria-label={
                  isOpen
                    ? t("space_settings_hide_models_named", { kind: title })
                    : t("space_settings_choose_models_named", { kind: title })
                }
              >
                {isOpen ? t("space_settings_hide_models") : t("space_settings_choose_models")}
                <ChevronDown
                  aria-hidden="true"
                  className={cn("size-4 transition-transform", isOpen && "rotate-180")}
                />
              </Button>
            </CollapsibleTrigger>
          ) : null}
        </div>
        {models.length === 0 ? (
          <p className="text-muted-foreground w-full text-sm">{t("no_models_found")}</p>
        ) : selectedPreview.length > 0 ? (
          <ul className="flex w-full flex-wrap gap-1.5 text-xs">
            {selectedPreview.map((model) => (
              <li key={model.id} className="bg-muted rounded-md px-2 py-1 font-medium break-all">
                {label(model)}
              </li>
            ))}
            {moreSelected > 0 ? (
              <li className="text-muted-foreground px-2 py-1">
                {t("space_settings_more_models", { count: moreSelected })}
              </li>
            ) : null}
          </ul>
        ) : null}
      </div>

      <CollapsibleContent className="border-t p-4">
        <div className="flex flex-col gap-2">
          {models.length > SEARCH_THRESHOLD && (
            <ResourceFilterInput
              inputRef={searchRef}
              value={search}
              onChange={setSearch}
              label={t("search_models_and_providers")}
              placeholder={t("search_models_and_providers")}
              resultCount={visibleGroups.reduce((count, group) => count + group.visible.length, 0)}
              className="max-w-none"
            />
          )}

          {searching && visibleGroups.length === 0 && (
            <div className="border-ax-border rounded-ax-element flex flex-col items-start gap-2 border p-4">
              <p className="text-ax-text-secondary text-sm">{t("space_models_no_matches")}</p>
              <AstryxButton
                label={t("space_models_clear_search")}
                variant="ghost"
                size="sm"
                onClick={() => {
                  setSearch("");
                  searchRef.current?.focus();
                }}
              />
            </div>
          )}

          {visibleGroups.map((group) => {
            const selectedCount = group.models.filter((model) => selected.has(model.id)).length;
            const selectable = group.models.filter(
              (model) => model.meets_security_classification ?? true
            );
            const allSelected =
              selectable.length > 0 && selectable.every((model) => selected.has(model.id));
            const isOpen = searching
              ? true
              : (openOverride[group.name] ?? (groups.length === 1 || selectedCount > 0));

            return (
              <Collapsible
                key={group.name}
                open={isOpen}
                onOpenChange={(open) =>
                  setOpenOverride((prev) => ({ ...prev, [group.name]: open }))
                }
                className="rounded-lg border"
              >
                <div className="flex items-center gap-2 px-3 py-2">
                  <CollapsibleTrigger className="flex min-w-0 flex-1 items-center gap-2 text-left">
                    <ChevronRight
                      className={cn(
                        "text-muted-foreground size-4 shrink-0 transition-transform",
                        isOpen && "rotate-90"
                      )}
                      aria-hidden="true"
                    />
                    <ProviderLogo
                      provider={group.models[0]?.provider_type ?? group.name}
                      className="size-5 shrink-0"
                    />
                    <span className="truncate text-sm font-medium">{group.name}</span>
                  </CollapsibleTrigger>
                  <span className="text-muted-foreground shrink-0 text-xs tabular-nums">
                    <span aria-hidden="true">
                      {selectedCount} / {group.models.length}
                    </span>
                    <span className="sr-only">
                      {t("models_selected_count", { count: selectedCount })}
                    </span>
                  </span>
                  <Button
                    type="button"
                    variant="ghost"
                    size="sm"
                    className="shrink-0"
                    disabled={selectable.length === 0}
                    onClick={() => setWholeGroup(group.models)}
                  >
                    {allSelected ? t("deselect_all") : t("select_all")}
                  </Button>
                </div>

                <CollapsibleContent className="space-model-collapse" inert={!isOpen}>
                  <div className="border-t">
                    {group.visible.map((model) => {
                      const meets = model.meets_security_classification ?? true;
                      const cost = costText(model, kind);
                      const reasonId = meets ? undefined : `${reasonPrefix}-${model.id}`;
                      return (
                        <div
                          key={model.id}
                          className="flex items-center gap-3 border-b px-3 py-2 last:border-b-0"
                        >
                          <div className="min-w-0 flex-1">
                            <span className="block truncate text-sm font-medium">
                              {label(model)}
                            </span>
                            {reasonId && (
                              <p id={reasonId} className="text-ax-text-secondary mt-0.5 text-xs">
                                {t("model_does_not_meet_security_classification")}
                              </p>
                            )}
                          </div>
                          <CapabilityIcons model={model} />
                          {cost && (
                            <span className="text-muted-foreground bg-muted inline-flex items-center rounded-md border px-1.5 py-0.5 font-mono text-[11px] tabular-nums">
                              {cost}
                            </span>
                          )}
                          <Switch
                            checked={selected.has(model.id)}
                            disabled={!meets}
                            onCheckedChange={() => toggleOne(model.id, group.name)}
                            aria-label={label(model)}
                            aria-describedby={reasonId}
                          />
                        </div>
                      );
                    })}
                  </div>
                </CollapsibleContent>
              </Collapsible>
            );
          })}
        </div>
      </CollapsibleContent>
    </Collapsible>
  );
}
