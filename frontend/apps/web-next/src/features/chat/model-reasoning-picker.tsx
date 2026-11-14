import { IconButton } from "@astryxdesign/core/IconButton";
import { RadioList, RadioListItem } from "@astryxdesign/core/RadioList";
import { ChevronDown, Lock, Search, X } from "lucide-react";
import { useTranslations } from "use-intl";
import { useMemo, useRef, useState } from "react";
import { KEYBOARD } from "@/components/astryx/keyboard-hints";
import { TextInput } from "@/components/astryx/text-input";
import {
  modelFacts,
  modelName,
  vendorLabel,
  type ModelRef
} from "@/components/ai-elements/model-selector";
import { ProviderLogo } from "@/components/ai-elements/provider-logo";
import { sortModels } from "@/features/ai-models/sort-models";
import type { Schema } from "@/lib/api/models";
import { cn } from "@/lib/utils";
import { ComposerPanel, useFitAbove, type ComposerPanelSurface } from "./composer-panel";
import { reasoningEffortLabel, reasoningEffortOptions } from "./reasoning-effort";

type CompletionModel = Schema<"CompletionModelPublic">;

const DEFAULT_LEVEL = "default";
/**
 * Arrow keys move a radio group's choice one row at a time, so a choice is
 * saved once it has rested this long, or when the panel closes: walking down
 * the list saves the model the person stops on, not each one passed.
 */
const SAVE_DELAY_MS = 300;
/** A list this short is read at a glance: the search comes with more models than this. */
const SEARCH_FROM = 8;

type Save<Value> = (value: Value) => void | Promise<unknown>;

/**
 * A choice shown at once and saved after a rest. A rejected save falls back
 * to the saved value (the caller reports the failure).
 */
function useRestedChoice<Value>(save: Save<Value>) {
  const [pending, setPending] = useState<{ value: Value } | null>(null);
  const waiting = useRef<{ timer: number; value: Value } | null>(null);

  const commit = (value: Value) => {
    waiting.current = null;
    void Promise.resolve(save(value))
      .catch(() => {})
      .finally(() => setPending((current) => (current?.value === value ? null : current)));
  };
  return {
    pending,
    choose(value: Value) {
      if (waiting.current) window.clearTimeout(waiting.current.timer);
      setPending({ value });
      waiting.current = {
        value,
        timer: window.setTimeout(() => commit(value), SAVE_DELAY_MS)
      };
    },
    /** Saves a choice still resting, now: a question sent next must wait for it. */
    flush() {
      const resting = waiting.current;
      if (!resting) return;
      window.clearTimeout(resting.timer);
      commit(resting.value);
    }
  };
}

export type ModelReasoningPickerProps = {
  models: CompletionModel[];
  selectedId: string | null | undefined;
  /** Saves a newly chosen model; a rejected save shows `selectedId` again. */
  onSelectModel: Save<string>;
  /** A model the governance policy pins: shown read-only, with a lock. */
  locked?: ModelRef | null;
  /** When false, input/output prices are hidden (org-controlled). */
  showPricing?: boolean;
  /** The reasoning level stored on the assistant, if any. */
  storedLevel: string | null;
  /** The organisation policy's default level, if any. */
  policyDefaultLevel: string | null;
  /** Saves a level, or null for the organisation default. */
  onSelectLevel: Save<string | null>;
};

/**
 * The personal chat composer's model picker where people may also choose the
 * reasoning level: one trigger for both, so the level costs the footer no
 * button of its own. The trigger shows the model, and the level only when it
 * is not the organisation's default. Its panel (a bottom sheet on phones)
 * holds two radio groups, "Chattmodell" with a search and "Resonemangsnivå"
 * with the levels the chosen model offers; a choice is saved without closing
 * the panel. A model without levels keeps the second group's place and says
 * so, so the panel does not change shape between models.
 */
export function ModelReasoningPicker({
  models,
  selectedId,
  onSelectModel,
  locked = null,
  showPricing = true,
  storedLevel,
  policyDefaultLevel,
  onSelectLevel
}: ModelReasoningPickerProps) {
  const t = useTranslations();
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const model = useRestedChoice(onSelectModel);
  const level = useRestedChoice(onSelectLevel);

  const sorted = useMemo(() => sortModels(models), [models]);
  const byId = useMemo(() => new Map(sorted.map((item) => [item.id, item])), [sorted]);
  const shownId = locked ? locked.id : (model.pending?.value ?? selectedId ?? null);
  const shown = shownId ? byId.get(shownId) : undefined;
  const shownName = locked
    ? modelName(locked)
    : shown
      ? modelName(shown)
      : shownId
        ? t("unsupported_model_selected")
        : t("select_a_model");

  const levels = reasoningEffortOptions(shown);
  const chosenLevel = level.pending ? level.pending.value : storedLevel;
  // The organisation's default, when the shown model offers it: that level's
  // row is the default's row, marked as such, so no level is listed twice.
  const policyLevel =
    policyDefaultLevel && levels.includes(policyDefaultLevel) ? policyDefaultLevel : null;
  // A level the shown model does not offer is not in force, and the
  // organisation's own level is its default whether stored or not.
  const ownLevel =
    chosenLevel && levels.includes(chosenLevel) && chosenLevel !== policyLevel ? chosenLevel : null;
  const ownLevelText = ownLevel ? reasoningEffortLabel(ownLevel, t) : null;

  const label = t("completion_model");
  const name = ownLevelText
    ? t("chat_model_with_reasoning_named", { label, model: shownName, level: ownLevelText })
    : t("chat_model_named", { label, model: shownName });

  const searchable = sorted.length >= SEARCH_FROM;
  const needle = query.trim().toLowerCase();
  const listed = needle
    ? sorted.filter((item) =>
        [modelName(item), item.name, vendorLabel(item, "")].some((text) =>
          text.toLowerCase().includes(needle)
        )
      )
    : sorted;

  const changeOpen = (next: boolean) => {
    if (!next) {
      model.flush();
      level.flush();
      setQuery("");
    }
    setOpen(next);
  };

  const content = ({ stacked, anchor, onClose }: ComposerPanelSurface) => (
    <PickerPanel
      stacked={stacked}
      anchor={anchor}
      onClose={onClose}
      title={label}
      filling={searchable}
    >
      <div className="flex min-h-0 min-w-0 flex-1 flex-col gap-2">
        {locked ? (
          <div className="flex flex-col gap-1">
            <p className="text-sm font-medium">{label}</p>
            <p className="flex items-center gap-2 text-[13px]">
              <Lock aria-hidden="true" className="text-ax-text-secondary size-3.5 shrink-0" />
              {shownName}
            </p>
            <p className="text-ax-text-secondary text-xs">{t("governance_locked_by_admin")}</p>
          </div>
        ) : (
          <>
            {searchable && (
              <TextInput
                label={t("search_models_and_providers")}
                isLabelHidden
                placeholder={t("search_models_and_providers")}
                value={query}
                onChange={setQuery}
                startIcon={Search}
                {...KEYBOARD.search}
                hasClear
                size="sm"
                width="100%"
              />
            )}
            <div className={cn("min-h-0 flex-auto overflow-y-auto pe-1", !stacked && "max-h-80")}>
              <RadioList
                label={label}
                // The sheet's title already says it.
                isLabelHidden={stacked}
                value={shownId ?? ""}
                onChange={(next) => {
                  if (next !== shownId) model.choose(next);
                }}
                size="sm"
                width="100%"
              >
                {listed.map((item) => (
                  <RadioListItem
                    key={item.id}
                    value={item.id}
                    align="start"
                    label={
                      <span className="flex min-w-0 items-center gap-2">
                        <ProviderLogo provider={item.org ?? item.provider_type} />
                        <span>{modelName(item)}</span>
                      </span>
                    }
                    description={[
                      vendorLabel(item, t("model_group_other")),
                      modelFacts(item, showPricing, t)
                    ]
                      .filter(Boolean)
                      .join(" · ")}
                  />
                ))}
              </RadioList>
              {listed.length === 0 && (
                <p className="text-ax-text-secondary py-2 text-sm">{t("no_models_found")}</p>
              )}
            </div>
          </>
        )}
      </div>

      <div
        className={cn(
          "border-ax-border flex shrink-0 flex-col gap-1",
          stacked ? "border-t pt-3" : "w-48 border-s ps-4"
        )}
      >
        {levels.length > 0 ? (
          <RadioList
            label={t("reasoning_effort")}
            value={ownLevel ?? policyLevel ?? DEFAULT_LEVEL}
            onChange={(next) => {
              // The default is saved as no level of one's own, so it follows the organisation's.
              const picked = next === DEFAULT_LEVEL || next === policyLevel ? null : next;
              if (picked !== ownLevel) level.choose(picked);
            }}
            size="sm"
            width="100%"
          >
            {/* Without a default the model offers, the model's own behaviour is the default. */}
            {!policyLevel && <RadioListItem value={DEFAULT_LEVEL} label={t("default_behavior")} />}
            {levels.map((option) => (
              <RadioListItem
                key={option}
                value={option}
                label={
                  option === policyLevel ? (
                    <span className="flex items-baseline gap-2">
                      {reasoningEffortLabel(option, t)}
                      <span className="text-ax-text-secondary text-xs">
                        {t("default_behavior")}
                      </span>
                    </span>
                  ) : (
                    reasoningEffortLabel(option, t)
                  )
                }
              />
            ))}
          </RadioList>
        ) : (
          <>
            <p className="text-sm font-medium">{t("reasoning_effort")}</p>
            <p className="text-ax-text-secondary text-xs">{t("reasoning_effort_not_offered")}</p>
          </>
        )}
      </div>
    </PickerPanel>
  );

  return (
    <ComposerPanel
      face={
        <>
          {locked ? (
            <Lock aria-hidden="true" className="size-[15px] shrink-0" />
          ) : (
            <ProviderLogo provider={shown?.org ?? shown?.provider_type} />
          )}
          {/* Below 640 px the provider's logo stands for the model: a name here
              pushed the send button off a 390 px screen. */}
          <span className="max-w-[min(12rem,30vw)] truncate max-sm:sr-only">{shownName}</span>{" "}
          {ownLevelText && (
            <span className="font-medium max-sm:sr-only">
              <span aria-hidden="true">· </span>
              {ownLevelText}
            </span>
          )}
          <ChevronDown aria-hidden="true" className="size-3.5 shrink-0" />
        </>
      }
      name={name}
      busy={model.pending !== null || level.pending !== null}
      label={label}
      open={open}
      onOpenChange={changeOpen}
      width={520}
      alignment="end"
      // A search field brings up the keyboard: only a tall sheet makes room for it.
      // Without one the sheet is as tall as its two lists.
      sheetHeight={searchable ? "tall" : "hug"}
    >
      {content}
    </ComposerPanel>
  );
}

/** The panel's frame: two columns beside the pill, one column with a title in the sheet. */
function PickerPanel({
  stacked,
  anchor,
  onClose,
  title,
  filling,
  children
}: ComposerPanelSurface & {
  title: string;
  /** In a tall sheet: take its height, so the model list scrolls above the levels. */
  filling: boolean;
  children: React.ReactNode;
}) {
  const t = useTranslations();
  const panel = useFitAbove(anchor);
  return (
    <div
      ref={panel}
      className={cn(
        "flex min-h-0 flex-col gap-3",
        stacked ? "p-4" : "p-1",
        stacked && filling && "h-full"
      )}
    >
      {onClose && (
        <div className="flex shrink-0 items-center justify-between gap-3">
          <p className="text-sm font-semibold">{title}</p>
          <IconButton
            label={t("close")}
            icon={<X aria-hidden="true" />}
            variant="ghost"
            onClick={onClose}
          />
        </div>
      )}
      <div className={cn("flex min-h-0 flex-auto gap-4", stacked && "flex-col")}>{children}</div>
    </div>
  );
}
