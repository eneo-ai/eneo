"use client";

import { BottomSheet } from "@astryxdesign/core/BottomSheet";
import { useMediaQuery } from "@astryxdesign/core/hooks";
import { ResizeHandle, useResizable } from "@astryxdesign/core/Resizable";
import { Activity, PanelRightOpen } from "lucide-react";
import { useTranslations } from "next-intl";
import { useEffect, useEffectEvent, useId, useRef, type ReactNode } from "react";
import { findAppCall } from "@/features/mcp-apps/mcp-apps";
import type { PreviewFile } from "@/features/workspace/preview/preview-kind";
import type { EneoUIMessage } from "@/lib/chat/types";
import { cn } from "@/lib/utils";
import type { DocumentExport } from "./document-export";
import type { DocumentSaver } from "./document-saver";
import { FilePanel } from "./file-panel";
import type { PanelContents } from "./panel-contents";
import { panelContentsCount } from "./panel-contents";
import { PanelContentsList, type ActivityEntry } from "./panel-contents-list";
import { PanelFrame, type PanelMaximise, type PanelSwitcher } from "./panel-frame";
import type { SidePanelStore } from "./side-panel-store";
import { ViewPanel } from "./view-panel";

export const SIDE_PANEL_ID = "chat-side-panel";
const WIDTH_STORAGE_KEY = "eneo:chat-side-panel-width";

/** The activity of an answer, shown by the chat view as the panel's occupant when nothing else is. */
export type ActivityOccupant = {
  /** The tabs and steps (ActivityPanelBody), rendered inside the frame. */
  body: ReactNode;
  detail: string;
  onClose: () => void;
};

export type SidePanelProps = {
  panel: SidePanelStore;
  messages: readonly EneoUIMessage[];
  contents: PanelContents;
  versionsOf: (file: PreviewFile) => PreviewFile[];
  exportOf: (file: PreviewFile) => DocumentExport | null;
  /** How a reader's edit of a file is saved, for a document that can be edited; null for any other file. */
  saverOf: (file: PreviewFile) => DocumentSaver | null;
  activity: ActivityOccupant | null;
  /** The latest answer's activity, for the switcher; null when there is none to show. */
  latestActivity: { detail: string; open: () => void } | null;
  children: ReactNode;
};

/**
 * The side region beside a conversation. It holds one occupant at a time: an
 * answer's activity, a document or uploaded file, an interactive tool view
 * covering that file, or the overview of everything the conversation has to
 * show. Beside the conversation from 1024px, with a handle to resize it and
 * a maximise over the conversation; below that a BottomSheet, except a view,
 * whose frame stays mounted in the message and is laid out over a cover.
 */
export function SidePanel({
  panel,
  messages,
  contents,
  versionsOf,
  exportOf,
  saverOf,
  activity,
  latestActivity,
  children
}: SidePanelProps) {
  const t = useTranslations();
  const panelId = useId();
  const beside = useMediaQuery("(min-width: 1024px)");
  const aside = useRef<HTMLElement>(null);
  const trigger = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    panel.setBesideConversation(beside);
  }, [panel, beside]);

  const occupant = panel.occupant;
  const kind = occupant.kind !== "closed" ? occupant.kind : activity ? "activity" : "closed";
  const shownView = occupant.kind === "view" ? findAppCall(messages, occupant.callId) : null;
  const hasContents = panelContentsCount(contents) > 0;
  const shown = kind !== "closed" && !(kind === "overview" && !hasContents);
  const maximised = panel.maximised && (kind === "file" || kind === "view");
  // The panel's width, a share of the row both halves share. The row is the
  // basis only while the panel can be beside the conversation: below that it
  // is phone-wide, and clamping the remembered width against it would lose it.
  const containerRef = useRef<HTMLDivElement>(null);
  const resizable = useResizable({
    containerRef,
    defaultSize: 520,
    minSize: 360,
    maxSize: "65%",
    autoSaveId: WIDTH_STORAGE_KEY
  });

  // A view whose call is gone (another conversation was opened, or it was
  // stopped) leaves the panel.
  useEffect(() => {
    if (occupant.kind === "view" && !shownView) panel.closeView();
  }, [occupant, shownView, panel]);

  // Focus moves into the panel when the reader opens a file or the overview,
  // so keyboard users land where the new content is; a panel that opened by
  // itself leaves the focus where the reader has it, and the activity body
  // focuses its own tab. Closing hands focus back to the opener (the store
  // does that for files), or to the panel button.
  const wasShown = useRef(false);
  useEffect(() => {
    const landsHere = kind === "file" || kind === "overview";
    if (shown && !wasShown.current && landsHere && !panel.openedByItself && beside) {
      aside.current?.focus();
    }
    if (!shown && wasShown.current && document.activeElement === document.body) {
      trigger.current?.focus();
    }
    wasShown.current = shown;
  }, [shown, kind, beside, panel.openedByItself]);

  const close = () => {
    if (occupant.kind === "view") panel.dismissView();
    else if (occupant.kind === "file") panel.close();
    else if (occupant.kind === "overview") panel.closeOverview();
    else activity?.onClose();
  };

  // Escape steps back: out of the maximised panel first, then out of the panel.
  const onEscape = useEffectEvent(() => {
    if (maximised) panel.setMaximised(false);
    else close();
  });
  useEffect(() => {
    const element = aside.current;
    if (!shown || !element) return;
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key !== "Escape" || event.defaultPrevented) return;
      event.preventDefault();
      onEscape();
    };
    element.addEventListener("keydown", onKeyDown);
    return () => element.removeEventListener("keydown", onKeyDown);
  }, [shown, beside, kind]);

  const activityEntry: ActivityEntry | null = latestActivity
    ? {
        detail: latestActivity.detail,
        shown: kind === "activity",
        open: () => {
          panel.closeAll();
          latestActivity.open();
        }
      }
    : null;

  const switcher: PanelSwitcher | null =
    hasContents || activityEntry
      ? {
          panel,
          contents,
          activity: activityEntry,
          onFile: (file) => {
            activity?.onClose();
            panel.open(file, trigger.current);
          },
          onView: (view) => {
            activity?.onClose();
            view.open();
          }
        }
      : null;

  const maximise: PanelMaximise | null =
    beside && (kind === "file" || kind === "view")
      ? { on: panel.maximised, toggle: () => panel.setMaximised(!panel.maximised) }
      : null;

  const body = (narrow: boolean) => {
    switch (kind) {
      case "file":
        return (
          <FilePanel
            panel={panel}
            versionsOf={versionsOf}
            exportOf={exportOf}
            saverOf={saverOf}
            switcher={switcher}
            maximise={maximise}
            narrow={narrow}
          />
        );
      case "view":
        return shownView ? (
          <ViewPanel panel={panel} call={shownView.call} switcher={switcher} maximise={maximise} />
        ) : null;
      case "overview":
        return (
          <PanelFrame
            icon={<PanelRightOpen className="size-4" />}
            tileClassName="bg-ax-muted text-ax-text-secondary"
            title={t("conversation_panel_title")}
            switcher={null}
            maximise={null}
            onClose={() => panel.closeOverview()}
            closeLabel={t("conversation_panel_close")}
          >
            <div className="min-h-0 flex-1 overflow-y-auto p-2">
              <PanelContentsList
                panel={panel}
                contents={contents}
                activity={activityEntry}
                focusSection={occupant.kind === "overview" ? occupant.section : null}
                onFile={(file) => panel.open(file, trigger.current)}
                onView={(view) => view.open()}
              />
            </div>
          </PanelFrame>
        );
      case "activity":
        return activity ? (
          <PanelFrame
            icon={<Activity className="size-4" />}
            tileClassName="bg-ax-muted text-ax-text-secondary"
            title={t("chat_activity_label")}
            detail={activity.detail}
            switcher={switcher}
            maximise={null}
            onClose={activity.onClose}
            closeLabel={t("chat_activity_close")}
          >
            {activity.body}
          </PanelFrame>
        ) : null;
      default:
        return null;
    }
  };

  const label =
    kind === "view"
      ? t("mcp_app_view_title")
      : kind === "file"
        ? t("file_preview_title")
        : kind === "activity"
          ? t("chat_activity_panel_label")
          : t("conversation_panel_title");

  // The panel's own way in: a button above the conversation while it is closed.
  const launcher = hasContents && !shown && (
    // The conversation's scrollbar runs along this edge; the button keeps clear of it.
    <div className="pointer-events-none absolute inset-x-0 top-0 z-10 flex justify-end pt-2 pr-7 pl-4">
      <button
        ref={trigger}
        type="button"
        aria-label={t("conversation_panel_open")}
        aria-expanded={false}
        aria-controls={panelId}
        onClick={() => {
          activity?.onClose();
          panel.showOverview(null, trigger.current);
        }}
        className="text-ax-text-secondary hover:text-ax-text hover:bg-ax-hover focus-visible:outline-ring rounded-ax-element bg-ax-surface border-ax-border shadow-ax-low pointer-events-auto inline-flex h-8 items-center gap-2 border px-2.5 text-[13px] font-medium focus-visible:outline-2 focus-visible:outline-offset-2 pointer-coarse:h-11"
      >
        <PanelRightOpen aria-hidden="true" className="size-4" />
        {t("conversation_panel_title")}
      </button>
    </div>
  );

  return (
    <div ref={beside ? containerRef : null} className="relative flex min-h-0 min-w-0 flex-1">
      {/* No stacking context of its own: a view's frame lives in a message here
          and is laid out over the panel, so it must be able to paint above it. */}
      <div className="relative flex min-h-0 min-w-0 flex-1 flex-col">
        {launcher}
        {children}
      </div>
      {shown && beside && (
        <>
          {/* The panel sits at the end of the row: dragging the handle left widens it. */}
          <ResizeHandle
            isReversed
            hasDivider
            label={t("file_preview_resize_handle")}
            resizable={resizable.props}
          />
          <aside
            ref={aside}
            id={panelId}
            aria-label={label}
            tabIndex={-1}
            style={maximised ? undefined : { width: resizable.size }}
            className={cn(
              "bg-ax-surface flex min-h-0 shrink-0 flex-col focus-visible:outline-none",
              maximised ? "absolute inset-0 z-20" : "relative h-full"
            )}
          >
            {body(false)}
          </aside>
        </>
      )}
      {shown && !beside && kind === "view" && (
        // The app remains mounted in the conversation, so this is a non-modal
        // cover: a dialog's focus trap would exclude the visually expanded iframe.
        <aside
          ref={aside}
          id={panelId}
          aria-label={label}
          tabIndex={-1}
          className="bg-ax-surface fixed inset-0 z-20 flex min-h-0 flex-col"
        >
          {body(true)}
        </aside>
      )}
      {shown && !beside && kind !== "view" && (
        <BottomSheet
          isOpen
          onOpenChange={(open) => {
            if (!open) close();
          }}
          label={label}
          height="tall"
          padding={0}
        >
          <div id={panelId} className="flex h-full min-h-0 flex-col">
            {body(true)}
          </div>
        </BottomSheet>
      )}
    </div>
  );
}
