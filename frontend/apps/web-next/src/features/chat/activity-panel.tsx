"use client";

import { Tab, TabList } from "@astryxdesign/core/TabList";
import { useLocale, useTranslations } from "use-intl";
import { useEffect, useRef } from "react";
import type { Activity } from "./activity";
import { SourceList, sourceAnchorId } from "./activity-sources";
import { StepList } from "./activity-steps";
import type { TurnDurations } from "./activity-timings";
import { DebugTabPanel, type DebugTabConfig } from "./debug-panel";
import { formatSeconds } from "./format";

export type ActivityTab = "steps" | "sources" | "debug";

export const ACTIVITY_PANEL_ID = "chat-activity-panel";

export type ActivityPanelProps = {
  messageId: string;
  activity: Activity;
  durations: TurnDurations | null;
  sessionId: string | null;
  tab: ActivityTab;
  onTabChange: (tab: ActivityTab) => void;
  /** 0-based source to focus (opened from an inline citation). */
  focusSource: number | null;
  /** The Felsök tab (users with `assistant_debug`, saved conversations only). */
  debug?: DebugTabConfig | null;
  /**
   * Whether the body may move focus for `key` (an answer, and the source asked
   * for), recording that it did. Kept by the caller: a change of presentation
   * (sheet, beside) mounts the body again, which must not move focus again
   * (F7). Without it, the body keeps its own record.
   */
  claimFocus?: (key: string) => boolean;
};

/**
 * The Aktivitet panel's body: steps (timeline with tool calls, sources read,
 * approvals, durations when known), numbered sources and, for users who may
 * debug assistants, the Felsök tab with the saved turn's diagnostics. It is
 * an occupant of the chat's side panel (side-panel/side-panel.tsx), which
 * owns the aside, the sheet, the title and the close button. Focus moves to
 * the selected tab once per opened answer; a citation that targets a source
 * focuses that source instead.
 */
export function ActivityPanelBody({
  messageId,
  activity,
  durations,
  sessionId,
  tab: requestedTab,
  onTabChange,
  focusSource,
  debug = null,
  claimFocus
}: ActivityPanelProps) {
  const t = useTranslations();
  const locale = useLocale();
  const tabListRef = useRef<HTMLDivElement>(null);
  const focusedFor = useRef<string | null>(null);
  // A debug tab asked for without the right (or for an unsaved conversation)
  // shows the steps instead.
  const tab = requestedTab === "debug" && !debug ? "steps" : requestedTab;
  const stepsPanelId = `${ACTIVITY_PANEL_ID}-steps`;
  const sourcesPanelId = `${ACTIVITY_PANEL_ID}-sources`;
  const debugPanelId = `${ACTIVITY_PANEL_ID}-debug`;
  const steps = activity.steps.length;

  // Focus moves once per opened answer (WCAG 2.4.3): to the source a citation
  // asked for, else to the selected tab. In a modal sheet this runs before the
  // sheet's dialog opens, and nothing in a closed dialog takes focus; the
  // sheet opens in its own effect, later in the same task: focus right after.
  useEffect(() => {
    const source = tab === "sources" ? focusSource : null;
    const key = `${messageId}:${source ?? ""}`;
    if (claimFocus) {
      if (!claimFocus(key)) return;
    } else {
      if (focusedFor.current === key) return;
      focusedFor.current = key;
    }
    const target =
      source === null
        ? tabListRef.current?.querySelector<HTMLElement>('[role="tab"][aria-selected="true"]')
        : document.getElementById(sourceAnchorId(messageId, source + 1));
    if (!target) return;
    const focus = () => {
      target.focus();
      if (source !== null) target.scrollIntoView({ block: "nearest" });
    };
    if (target.closest("dialog:not([open])")) queueMicrotask(focus);
    else focus();
  }, [messageId, tab, focusSource, claimFocus]);

  return (
    <div id={ACTIVITY_PANEL_ID} className="flex min-h-0 flex-1 flex-col">
      <div className="border-ax-border flex min-h-[44px] shrink-0 items-center justify-between gap-2 border-b ps-3.5 pe-2.5">
        <div ref={tabListRef}>
          <TabList
            value={tab}
            onChange={(value) =>
              onTabChange(value === "sources" ? "sources" : value === "debug" ? "debug" : "steps")
            }
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
            {debug && <Tab value="debug" label={t("chat_debug_action")} panelId={debugPanelId} />}
          </TabList>
        </div>
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
        <SourceList messageId={messageId} sources={activity.sources} />
      </div>
      {/* Mounted only while shown: its queries run the first time the tab opens. */}
      {debug && tab === "debug" && (
        <div
          id={debugPanelId}
          role="tabpanel"
          aria-label={t("chat_debug_action")}
          tabIndex={0}
          className="focus-visible:outline-ring min-h-0 flex-1 overflow-y-auto px-4 pt-3 pb-4 focus-visible:outline-2 focus-visible:-outline-offset-2"
        >
          <DebugTabPanel
            messageId={messageId}
            sessionId={debug.sessionId}
            onSelectTurn={debug.onSelectTurn}
          />
        </div>
      )}

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
