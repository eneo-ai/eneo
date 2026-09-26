"use client";

import { BottomSheet } from "@astryxdesign/core/BottomSheet";
import { IconButton } from "@astryxdesign/core/IconButton";
import { Tab, TabList } from "@astryxdesign/core/TabList";
import { X } from "lucide-react";
import { useLocale, useTranslations } from "next-intl";
import { useEffect, useId, useRef, type Ref } from "react";
import type { Activity } from "./activity";
import { SourceList } from "./activity-sources";
import { StepList } from "./activity-steps";
import type { TurnDurations } from "./activity-timings";
import { formatSeconds } from "./format";

export type ActivityTab = "steps" | "sources";

export const ACTIVITY_PANEL_ID = "chat-activity-panel";

function PanelBody({
  id,
  messageId,
  activity,
  durations,
  sessionId,
  tab,
  onTabChange,
  focusSource,
  onClose,
  tabListRef
}: {
  /** The panel id the activity pill's aria-controls points at (sheet variant). */
  id?: string;
  messageId: string;
  activity: Activity;
  durations: TurnDurations | null;
  sessionId: string | null;
  tab: ActivityTab;
  onTabChange: (tab: ActivityTab) => void;
  focusSource: number | null;
  onClose: () => void;
  tabListRef?: Ref<HTMLDivElement>;
}) {
  const t = useTranslations();
  const locale = useLocale();
  const stepsPanelId = `${ACTIVITY_PANEL_ID}-steps`;
  const sourcesPanelId = `${ACTIVITY_PANEL_ID}-sources`;
  const steps = activity.steps.length;

  return (
    <div id={id} className="flex min-h-0 flex-1 flex-col">
      <div className="border-ax-border flex min-h-[52px] shrink-0 items-center justify-between gap-2 border-b ps-3.5 pe-2.5">
        <div ref={tabListRef}>
          <TabList
            value={tab}
            onChange={(value) => onTabChange(value === "sources" ? "sources" : "steps")}
            role="tablist"
            size="sm"
            aria-label={t("chat_activity_label")}
          >
            <Tab value="steps" label={t("chat_activity_steps_tab")} panelId={stepsPanelId} />
            <Tab
              value="sources"
              label={t("chat_sources_label")}
              panelId={sourcesPanelId}
              endContent={
                <span className="bg-ax-surface text-ax-text-secondary rounded-full px-1.5 text-[11px] font-bold tabular-nums">
                  {activity.sources.length}
                </span>
              }
            />
          </TabList>
        </div>
        <IconButton
          label={t("chat_activity_close")}
          icon={<X className="size-4" />}
          variant="ghost"
          size="sm"
          onClick={onClose}
        />
      </div>

      <div
        id={stepsPanelId}
        role="tabpanel"
        aria-label={t("chat_activity_steps_tab")}
        tabIndex={0}
        hidden={tab !== "steps"}
        className="focus-visible:outline-ring min-h-0 flex-1 overflow-y-auto px-4 pt-[18px] pb-4 focus-visible:outline-2 focus-visible:-outline-offset-2"
      >
        <StepList activity={activity} durations={durations} sessionId={sessionId} />
      </div>
      <div
        id={sourcesPanelId}
        role="tabpanel"
        aria-label={t("chat_sources_label")}
        tabIndex={0}
        hidden={tab !== "sources"}
        className="focus-visible:outline-ring min-h-0 flex-1 overflow-y-auto p-3 focus-visible:outline-2 focus-visible:-outline-offset-2"
      >
        <SourceList
          messageId={messageId}
          sources={activity.sources}
          focusIndex={tab === "sources" ? focusSource : null}
        />
      </div>

      <div className="border-ax-border text-ax-text-secondary flex shrink-0 justify-between gap-2 border-t px-4 py-3 text-xs">
        <span>
          {durations?.totalMs != null
            ? t("chat_activity_total", { duration: formatSeconds(durations.totalMs, locale) })
            : null}
        </span>
        <span>
          {t("chat_activity_steps", { count: steps })} ·{" "}
          {activity.errorCount > 0
            ? t("chat_activity_errors", { count: activity.errorCount })
            : t("chat_activity_no_errors")}
        </span>
      </div>
    </div>
  );
}

export type ActivityPanelProps = {
  messageId: string;
  activity: Activity;
  durations: TurnDurations | null;
  sessionId: string | null;
  tab: ActivityTab;
  onTabChange: (tab: ActivityTab) => void;
  /** 0-based source to focus (opened from an inline citation). */
  focusSource: number | null;
  onClose: () => void;
  /** Inline side panel (≥1024px) or a modal bottom sheet (smaller screens). */
  variant: "side" | "sheet";
};

/**
 * The Aktivitet panel: steps (timeline with tool calls, sources read,
 * approvals, durations when known) and numbered sources. Side panel on wide
 * screens, bottom sheet on tablets and phones. Focus moves into it when it
 * opens; Escape and the close button close it (the caller returns focus to
 * the pill that opened it).
 */
export function ActivityPanel({ variant, onClose, ...props }: ActivityPanelProps) {
  const t = useTranslations();
  const titleId = useId();
  const asideRef = useRef<HTMLElement>(null);
  const tabListRef = useRef<HTMLDivElement>(null);
  const focusedFor = useRef<string | null>(null);
  const { focusSource, tab, messageId } = props;

  // Side panel: move focus in once per opened answer (the sheet's dialog does
  // this itself). A citation that targets a source focuses that source instead.
  useEffect(() => {
    if (variant !== "side" || focusedFor.current === messageId) return;
    focusedFor.current = messageId;
    if (tab === "sources" && focusSource !== null) return;
    tabListRef.current?.querySelector<HTMLElement>('[role="tab"][aria-selected="true"]')?.focus();
  }, [variant, messageId, tab, focusSource]);

  // Escape closes the side panel from anywhere inside it.
  useEffect(() => {
    const aside = asideRef.current;
    if (variant !== "side" || !aside) return;
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key !== "Escape" || event.defaultPrevented) return;
      event.preventDefault();
      onClose();
    };
    aside.addEventListener("keydown", onKeyDown);
    return () => aside.removeEventListener("keydown", onKeyDown);
  }, [variant, onClose]);

  if (variant === "sheet") {
    return (
      <BottomSheet
        isOpen
        onOpenChange={(open) => {
          if (!open) onClose();
        }}
        label={t("chat_activity_panel_label")}
        height="tall"
      >
        <PanelBody {...props} id={ACTIVITY_PANEL_ID} onClose={onClose} />
      </BottomSheet>
    );
  }

  return (
    <aside
      ref={asideRef}
      id={ACTIVITY_PANEL_ID}
      aria-labelledby={titleId}
      className="bg-ax-sunken border-ax-border flex w-[340px] shrink-0 flex-col border-s"
    >
      <h2 id={titleId} className="sr-only">
        {t("chat_activity_panel_label")}
      </h2>
      <PanelBody {...props} onClose={onClose} tabListRef={tabListRef} />
    </aside>
  );
}
