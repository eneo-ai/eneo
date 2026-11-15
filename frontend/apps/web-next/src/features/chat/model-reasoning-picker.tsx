import { useAnnounce } from "@astryxdesign/core/hooks";
import { IconButton } from "@astryxdesign/core/IconButton";
import { RadioList, RadioListItem } from "@astryxdesign/core/RadioList";
import { ChevronDown, Lock, Search, X } from "lucide-react";
import { useTranslations } from "use-intl";
import { useEffect, useMemo, useRef, useState } from "react";
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
import { queuePartnerUpdate } from "./partner-updates";
import {
  effectiveReasoningEffort,
  reasoningEffortLabel,
  reasoningEffortOptions
} from "./reasoning-effort";

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

/** The model and the level as one choice; the level is null for the organisation's default. */
type Choice = { modelId: string | null; level: string | null };
/** What a save changes: only the parts the person changed. */
export type ModelReasoningChange = { modelId?: string; level?: string | null };

/**
 * The model and the level, shown at once and saved together after a rest, in
 * one update with the parts that changed. A level chosen for a model passed
 * over is not saved: only the levels the model rested on count, so the backend
 * never checks a level against the wrong model. Each choice has an id, and
 * only the save of the latest one ends the waiting state, so an older save
 * that settles late never shows an older choice. A rejected save falls back to
 * the saved choice (the caller reports the failure).
 */
function useRestedChoice(
  saved: Choice,
  save: (change: ModelReasoningChange) => void | Promise<unknown>,
  levelsOf: (modelId: string | null) => string[]
) {
  const [pending, setPending] = useState<{ id: number; choice: Choice } | null>(null);
  // What was shown when the rest began (a save still under way included), what
  // is chosen now, and the place it holds in the save queue.
  const resting = useRef<{
    timer: number;
    id: number;
    from: Choice;
    choice: Choice;
    rested: () => void;
  } | null>(null);
  const lastId = useRef(0);
  // The latest save, which a choice that changes nothing waits for.
  const lastSave = useRef<Promise<unknown>>(Promise.resolve());
  const shown = pending?.choice ?? saved;
  // A choice still resting when the picker goes is saved, so its place in the queue is let go.
  const commitRef = useRef<() => void>(() => {});
  useEffect(() => () => commitRef.current(), []);

  const commit = () => {
    const rest = resting.current;
    if (!rest) return;
    resting.current = null;
    window.clearTimeout(rest.timer);
    const { id, from, choice } = rest;
    const change: ModelReasoningChange = {};
    if (choice.modelId !== null && choice.modelId !== from.modelId) change.modelId = choice.modelId;
    const levels = levelsOf(choice.modelId);
    if (
      choice.level !== from.level &&
      levels.length > 0 &&
      (choice.level === null || levels.includes(choice.level))
    ) {
      change.level = choice.level;
    }
    if (Object.keys(change).length > 0) {
      lastSave.current = Promise.resolve(save(change)).catch(() => {});
    }
    // Queued behind its place, the save now holds the questions sent meanwhile.
    rest.rested();
    void lastSave.current.finally(() =>
      setPending((current) => (current?.id === id ? null : current))
    );
  };
  useEffect(() => {
    commitRef.current = commit;
  });
  return {
    shown,
    busy: pending !== null,
    choose(part: Partial<Choice>) {
      const id = ++lastId.current;
      const from = resting.current?.from ?? shown;
      const choice = { ...(resting.current?.choice ?? shown), ...part };
      let rested = resting.current?.rested;
      if (resting.current) window.clearTimeout(resting.current.timer);
      else {
        // A question sent while the choice rests (Send pressed with the panel
        // open, before the panel closes) waits for its save, not just for
        // saves already made.
        const place = new Promise<void>((resolve) => (rested = resolve));
        void queuePartnerUpdate(() => place);
      }
      setPending({ id, choice });
      resting.current = {
        id,
        from,
        choice,
        rested: rested!,
        timer: window.setTimeout(commit, SAVE_DELAY_MS)
      };
    },
    /** Saves a choice still resting, now: a question sent next must wait for it. */
    flush: commit
  };
}

/** The models whose name or provider holds the search. */
function matching(models: CompletionModel[], search: string): CompletionModel[] {
  const needle = search.trim().toLowerCase();
  if (!needle) return models;
  return models.filter((item) =>
    [modelName(item), item.name, vendorLabel(item, "")].some((text) =>
      text.toLowerCase().includes(needle)
    )
  );
}

/**
 * Scrolls the chosen model into the list's view as the panel opens: with a
 * long list it is often below the edge. A frame later, once the panel is shown
 * and has its height.
 */
function bringChosenIntoView(list: HTMLDivElement | null) {
  if (!list) return;
  const frame = requestAnimationFrame(() => {
    const chosen = list.querySelector<HTMLInputElement>('input[type="radio"]:checked');
    (chosen?.closest("label") ?? chosen)?.scrollIntoView({ block: "nearest" });
  });
  return () => cancelAnimationFrame(frame);
}

export type ModelReasoningPickerProps = {
  models: CompletionModel[];
  selectedId: string | null | undefined;
  /** A model the governance policy pins: shown read-only, with a lock. */
  locked?: ModelRef | null;
  /** When false, input/output prices are hidden (org-controlled). */
  showPricing?: boolean;
  /** The reasoning level stored on the assistant, if any. */
  storedLevel: string | null;
  /** The organisation policy's default level, if any. */
  policyDefaultLevel: string | null;
  /**
   * Saves what changed in one update: the model, the level (null for the
   * organisation default), or both. A rejected save shows the stored choice again.
   */
  onSave: (change: ModelReasoningChange) => void | Promise<unknown>;
};

/**
 * The personal chat composer's model picker where people may also choose the
 * reasoning level: one trigger for both, so the level costs the footer no
 * button of its own. The trigger shows the model, and the level only when the
 * account has one of its own. Its panel (a bottom sheet on phones) holds two
 * radio groups, "Chattmodell" with a search and "Resonemangsnivå" with
 * "Standard" (the organisation's level, which it follows) and the levels the
 * chosen model offers; a choice is saved without closing
 * the panel. A model without levels keeps the second group's place and says
 * so, so the panel does not change shape between models.
 */
export function ModelReasoningPicker({
  models,
  selectedId,
  locked = null,
  showPricing = true,
  storedLevel,
  policyDefaultLevel,
  onSave
}: ModelReasoningPickerProps) {
  const t = useTranslations();
  const announce = useAnnounce();
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");

  const sorted = useMemo(() => sortModels(models), [models]);
  const byId = useMemo(() => new Map(sorted.map((item) => [item.id, item])), [sorted]);
  const choice = useRestedChoice(
    { modelId: locked ? locked.id : (selectedId ?? null), level: storedLevel },
    onSave,
    (id) => reasoningEffortOptions(id ? byId.get(id) : undefined)
  );
  const shownId = choice.shown.modelId;
  const shown = shownId ? byId.get(shownId) : undefined;
  const shownName = locked
    ? modelName(locked)
    : shown
      ? modelName(shown)
      : shownId
        ? t("unsupported_model_selected")
        : t("select_a_model");

  const levels = reasoningEffortOptions(shown);
  const chosenLevel = choice.shown.level;
  // The organisation's default, when the shown model offers it: named on the
  // default's row, which follows the organisation when it changes its level.
  const policyLevel = effectiveReasoningEffort({
    stored: null,
    policyDefault: policyDefaultLevel,
    options: levels
  });
  // The account's own level, also when it is the same as the organisation's:
  // only "Standard" follows a changed default. A level the shown model does
  // not offer is not in force.
  const ownLevel = effectiveReasoningEffort({
    stored: chosenLevel,
    policyDefault: null,
    options: levels
  });
  const ownLevelText = ownLevel ? reasoningEffortLabel(ownLevel, t) : null;

  const label = t("completion_model");
  const name = ownLevelText
    ? t("chat_model_with_reasoning_named", { label, model: shownName, level: ownLevelText })
    : t("chat_model_named", { label, model: shownName });

  const searchable = sorted.length >= SEARCH_FROM;
  const listed = matching(sorted, query);
  // The list changes without moving focus: say what the search found (WCAG 4.1.3).
  const search = (next: string) => {
    setQuery(next);
    if (!next.trim()) return;
    const found = matching(sorted, next).length;
    announce(found > 0 ? t("models_found_count", { count: found }) : t("no_models_found"));
  };

  const changeOpen = (next: boolean) => {
    if (!next) {
      choice.flush();
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
            {/* Beside the pill the column's heading stands above the search, level with the
                level column's, and stays as the list scrolls; the group keeps it as its name.
                The sheet's title says it there. */}
            {!stacked && (
              <p aria-hidden="true" className="text-ax-text-secondary text-sm font-medium">
                {label}
              </p>
            )}
            {searchable && (
              <TextInput
                label={t("search_models_and_providers")}
                isLabelHidden
                placeholder={t("search_models_and_providers")}
                value={query}
                onChange={search}
                startIcon={Search}
                {...KEYBOARD.search}
                hasClear
                size="sm"
                width="100%"
              />
            )}
            <div
              ref={bringChosenIntoView}
              className={cn(
                "scroll-fade min-h-0 flex-auto overflow-y-auto pe-1",
                // Beside the pill, a list with a search keeps its height, so the
                // panel neither shrinks nor moves as the search narrows it.
                !stacked && (searchable ? "h-80" : "max-h-80"),
                // In a short sheet, the list keeps rows to choose from; the sheet scrolls to the levels.
                stacked && "min-h-40"
              )}
            >
              <RadioList
                label={label}
                isLabelHidden
                value={shownId ?? ""}
                onChange={(next) => {
                  if (next !== shownId) choice.choose({ modelId: next });
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
            value={ownLevel ?? DEFAULT_LEVEL}
            onChange={(next) => {
              // The default is saved as no level of one's own, so it follows the organisation's.
              const picked = next === DEFAULT_LEVEL ? null : next;
              if (picked !== ownLevel) choice.choose({ level: picked });
            }}
            size="sm"
            width="100%"
          >
            {/* The organisation's level, named; without one the model offers, the model's own behaviour. */}
            <RadioListItem
              value={DEFAULT_LEVEL}
              label={
                <span className="flex items-baseline gap-2">
                  {t("default_behavior")}
                  {policyLevel && (
                    <span className="text-ax-text-secondary text-xs">
                      {reasoningEffortLabel(policyLevel, t)}
                    </span>
                  )}
                </span>
              }
            />
            {levels.map((option) => (
              <RadioListItem key={option} value={option} label={reasoningEffortLabel(option, t)} />
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
          {/* The dot is an item of its own, so the pill's gap sets the room on both sides;
              the level is quieter than the model's name. */}
          {ownLevelText && (
            <>
              <span aria-hidden="true" className="max-sm:hidden">
                ·
              </span>{" "}
              <span className="text-ax-text-tertiary font-medium max-sm:sr-only">
                {ownLevelText}
              </span>
            </>
          )}
          <ChevronDown aria-hidden="true" className="size-3.5 shrink-0" />
        </>
      }
      name={name}
      busy={choice.busy}
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
