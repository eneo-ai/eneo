"use client";

import { Brain, ChevronDown, ChevronRight, Eye, Wrench } from "lucide-react";
import { useTranslations } from "next-intl";
import { useMemo, useState } from "react";
import { ProviderLogo } from "@/components/ai-elements/provider-logo";
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
 * Space model availability picker. The closed card shows the current selection;
 * opening it reveals the existing per-vendor controls and autosave behaviour.
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
  const [isOpen, setIsOpen] = useState(false);
  const [search, setSearch] = useState("");
  const [openOverride, setOpenOverride] = useState<Record<string, boolean>>({});

  const selected = useMemo(() => new Set(selectedIds), [selectedIds]);
  const selectedModels = models.filter((model) => selected.has(model.id));
  const selectedPreview = selectedModels.slice(0, 2);
  const moreSelected = selectedIds.length - selectedPreview.length;
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

  // The control whose change is saving: busy, it stays enabled so it keeps
  // focus; while a change saves, presses are ignored.
  const [changing, setChanging] = useState<string | null>(null);
  function change(control: string, ids: string[]) {
    if (pending) return;
    setChanging(control);
    onChange(ids);
  }
  const busyOn = (control: string) => (pending && changing === control) || undefined;

  function toggleOne(id: string) {
    change(
      `model:${id}`,
      selected.has(id) ? selectedIds.filter((x) => x !== id) : [...selectedIds, id]
    );
  }

  function setWholeGroup(group: string, groupModels: SelectableModel[], on: boolean) {
    const ids = groupModels
      .filter((model) => model.meets_security_classification ?? true)
      .map((model) => model.id);
    if (on) {
      const merged = new Set(selectedIds);
      ids.forEach((id) => merged.add(id));
      change(`group:${group}`, [...merged]);
    } else {
      const remove = new Set(ids);
      change(
        `group:${group}`,
        selectedIds.filter((id) => !remove.has(id))
      );
    }
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
                    disabled={selectable.length === 0}
                    aria-busy={busyOn(`group:${group.name}`)}
                    onClick={() => setWholeGroup(group.name, group.models, !allSelected)}
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
                          title={
                            meets ? undefined : t("model_does_not_meet_security_classification")
                          }
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
                            disabled={!meets}
                            aria-busy={busyOn(`model:${model.id}`)}
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
      </CollapsibleContent>
    </Collapsible>
  );
}
