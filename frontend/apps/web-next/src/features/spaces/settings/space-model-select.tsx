"use client";

import { Brain, ChevronRight, Eye, Wrench } from "lucide-react";
import { useTranslations } from "next-intl";
import { useMemo, useState } from "react";
import { ProviderLogo } from "@/components/ai-elements/provider-logo";
import { SettingsRow } from "@/components/composites/settings-rows";
import { Button } from "@/components/ui/button";
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible";
import { Input } from "@/components/ui/input";
import { Switch } from "@/components/ui/switch";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import {
  formatCostPerMillionTokens,
  formatCostPerMinute
} from "@/features/ai-models/format-model-stats";
import { cn } from "@/lib/utils";

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

type ModelKind = "completion" | "embedding" | "transcription";

const SEARCH_THRESHOLD = 6;

function label(model: SelectableModel): string {
  return model.nickname ?? model.name;
}

function groupName(model: SelectableModel): string {
  const raw = model.org || model.provider_type || "Other";
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
 * Space model availability picker. Models are grouped by vendor into collapsible
 * sections — each header shows a "selected / total" count plus a per-vendor
 * select-all, so the page stays short even with many models. Rows carry the same
 * capability icons + cost chip as the admin table. A search appears once a list
 * grows past a handful of models.
 */
export function SpaceModelSelect({
  models,
  selectedIds,
  title,
  description,
  kind,
  pending,
  onChange
}: {
  models: SelectableModel[];
  selectedIds: string[];
  title: string;
  description: string;
  kind: ModelKind;
  pending: boolean;
  onChange: (ids: string[]) => void;
}) {
  const t = useTranslations();
  const [search, setSearch] = useState("");
  const [openOverride, setOpenOverride] = useState<Record<string, boolean>>({});

  const selected = useMemo(() => new Set(selectedIds), [selectedIds]);
  const query = search.trim().toLowerCase();
  const searching = query !== "";

  const groups = useMemo(() => {
    const map = new Map<string, SelectableModel[]>();
    for (const model of models) {
      const key = groupName(model);
      const list = map.get(key) ?? [];
      list.push(model);
      map.set(key, list);
    }
    return [...map.entries()].map(([name, list]) => ({ name, models: list }));
  }, [models]);

  function toggleOne(id: string) {
    onChange(selected.has(id) ? selectedIds.filter((x) => x !== id) : [...selectedIds, id]);
  }

  function setWholeGroup(groupModels: SelectableModel[], on: boolean) {
    const ids = groupModels
      .filter((model) => model.meets_security_classification ?? true)
      .map((model) => model.id);
    if (on) {
      const merged = new Set(selectedIds);
      ids.forEach((id) => merged.add(id));
      onChange([...merged]);
    } else {
      const remove = new Set(ids);
      onChange(selectedIds.filter((id) => !remove.has(id)));
    }
  }

  if (models.length === 0) {
    return (
      <SettingsRow title={title} description={description}>
        <p className="text-muted-foreground text-sm">{t("no_models_found")}</p>
      </SettingsRow>
    );
  }

  return (
    <SettingsRow title={title} description={description}>
      <div className="flex flex-col gap-2">
        {models.length > SEARCH_THRESHOLD && (
          <Input
            className="h-9"
            placeholder={t("search_models")}
            value={search}
            onChange={(event) => setSearch(event.target.value)}
            aria-label={t("search_models")}
          />
        )}

        {groups.map((group) => {
          const visible = searching
            ? group.models.filter((model) => label(model).toLowerCase().includes(query))
            : group.models;
          if (visible.length === 0) return null;

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
              onOpenChange={(open) => setOpenOverride((prev) => ({ ...prev, [group.name]: open }))}
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
                <span
                  className="text-muted-foreground shrink-0 text-xs tabular-nums"
                  aria-label={t("models_selected_count", { count: selectedCount })}
                >
                  {selectedCount} / {group.models.length}
                </span>
                <Button
                  type="button"
                  variant="ghost"
                  size="sm"
                  className="shrink-0"
                  disabled={pending || selectable.length === 0}
                  onClick={() => setWholeGroup(group.models, !allSelected)}
                >
                  {allSelected ? t("deselect_all") : t("select_all")}
                </Button>
              </div>

              <CollapsibleContent>
                <div className="border-t">
                  {visible.map((model) => {
                    const meets = model.meets_security_classification ?? true;
                    const cost = costText(model, kind);
                    return (
                      <div
                        key={model.id}
                        className={cn(
                          "flex items-center gap-3 border-b px-3 py-2 last:border-b-0",
                          !meets && "opacity-60"
                        )}
                        title={meets ? undefined : t("model_does_not_meet_security_classification")}
                      >
                        <span className="min-w-0 flex-1 truncate text-sm font-medium">
                          {label(model)}
                        </span>
                        <CapabilityIcons model={model} />
                        {cost && (
                          <span className="text-muted-foreground bg-muted inline-flex items-center rounded-md border px-1.5 py-0.5 font-mono text-[11px] tabular-nums">
                            {cost}
                          </span>
                        )}
                        <Switch
                          checked={selected.has(model.id)}
                          disabled={pending || !meets}
                          onCheckedChange={() => toggleOne(model.id)}
                          aria-label={label(model)}
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
    </SettingsRow>
  );
}
