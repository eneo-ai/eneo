"use client";

import { BottomSheet } from "@astryxdesign/core/BottomSheet";
import { Activity, PanelRightOpen } from "lucide-react";
import { useTranslations } from "next-intl";
import { useEffect, useEffectEvent, useId, useRef, type ReactNode, type RefObject } from "react";
import { findAppCall } from "@/features/mcp-apps/mcp-apps";
import type { PreviewFile } from "@/features/workspace/preview/preview-kind";
import type { EneoUIMessage } from "@/lib/chat/types";
import { useElementWidth } from "@/lib/hooks/use-element-width";
import { useResizableSplit } from "@/lib/hooks/use-resizable-split";
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

/** Decision 14: what the conversation keeps beside a panel or the history. */
export const CONVERSATION_MIN_WIDTH = 480;
const PANEL_MIN_WIDTH = 360;
/** The resize handle between the conversation and the panel. */
const HANDLE_WIDTH = 4;

/** Whether the panel fits beside a conversation that has `width` px; else it covers it. */
export const panelFitsBeside = (width: number) =>
  width - HANDLE_WIDTH - CONVERSATION_MIN_WIDTH >= PANEL_MIN_WIDTH;

/**
 * The row the panel shares with an aside of the page (the chat's history),
 * measured as a whole: what the aside takes from it is known before the
 * aside is gone, so the panel never shows in a presentation it is about to
 * leave.
 */
export type SidePanelLayout = {
  row: RefObject<HTMLElement | null>;
  /** The aside beside the conversation; `yields`: it closes when the panel opens. */
  aside: { width: number; yields: boolean } | null;
  /** The conversation is not on screen (another tab): nothing is laid over the page for it. */
  hidden?: boolean;
};

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
  /** Without one, the panel measures the region it shares with the conversation. */
  layout?: SidePanelLayout;
  /**
   * The conversation. As a function it is told, in the same render, whether
   * the panel is a sheet over its lower part (decision 28).
   */
  children: ReactNode | ((state: { sheetOver: boolean }) => ReactNode);
};

/**
 * The side region beside a conversation. It holds one occupant at a time: an
 * answer's activity, a document or uploaded file, an interactive tool view
 * covering that file, or the overview of everything the conversation has to
 * show. Beside the conversation when the conversation keeps 480 px beside
 * it (decision 14: measured on the region that holds both, not the window),
 * with a handle to resize it and a maximise over the conversation; otherwise
 * a BottomSheet (non-modal for an answer's activity, decision 28), except a
 * view, whose frame stays mounted in the message and is laid out over a
 * cover. Until that region is measured it is not beside.
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
  layout,
  children
}: SidePanelProps) {
  const t = useTranslations();
  const panelId = useId();
  const aside = useRef<HTMLElement>(null);
  const sheetPanel = useRef<HTMLDivElement>(null);
  const trigger = useRef<HTMLButtonElement>(null);
  const region = useRef<HTMLDivElement>(null);

  const occupant = panel.occupant;
  const kind = occupant.kind !== "closed" ? occupant.kind : activity ? "activity" : "closed";
  const shownView = occupant.kind === "view" ? findAppCall(messages, occupant.callId) : null;
  const hasContents = panelContentsCount(contents) > 0;
  const shown = kind !== "closed" && !(kind === "overview" && !hasContents);
  // The room beside the conversation: the row, less an aside that stays.
  const row = useElementWidth(layout?.row ?? region);
  const asideTakes = layout?.aside && !(layout.aside.yields && shown) ? layout.aside.width : 0;
  const { width, fits, separatorProps } = useResizableSplit({
    container: row === null ? null : row - asideTakes,
    storageKey: WIDTH_STORAGE_KEY,
    defaultWidth: 520,
    minWidth: PANEL_MIN_WIDTH,
    maxFraction: 0.65,
    minRemaining: HANDLE_WIDTH + CONVERSATION_MIN_WIDTH
  });
  const beside = fits === true;
  const maximised = beside && panel.maximised && (kind === "file" || kind === "view");

  useEffect(() => {
    panel.setBesideConversation(beside);
  }, [panel, beside]);

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
    if (!shown && wasShown.current) {
      // After the opener had its turn: a closed modal sheet lets it take focus
      // only once it is gone (side-panel-store.ts, returnFocus).
      requestAnimationFrame(() => {
        if (document.activeElement === document.body) trigger.current?.focus();
      });
    }
    wasShown.current = shown;
  }, [shown, kind, beside, panel.openedByItself]);

  // F7: a change of presentation (the region widened or narrowed) replaces
  // the panel's elements. Focus that was in the panel, and was lost with
  // them, goes along into the new one; focus elsewhere stays where it is; a
  // sheet is a dialog and takes the focus itself. A cover hides everything
  // but the view laid over it, so focus anywhere else moves into it. Tracked
  // with focusin, which removing an element never fires.
  const focusInPanel = useRef(false);
  useEffect(() => {
    const onFocusIn = (event: FocusEvent) => {
      const target = event.target as Node;
      focusInPanel.current = Boolean(
        aside.current?.contains(target) || sheetPanel.current?.contains(target)
      );
    };
    document.addEventListener("focusin", onFocusIn);
    return () => document.removeEventListener("focusin", onFocusIn);
  }, []);
  // Decision 28: where it cannot sit beside the conversation, an answer's
  // activity is a sheet without a scrim over the lower part, so the answer
  // stays readable above it; the chat view keeps what it covers inert
  // (ConversationLayout's `sheetOver`). Files and views cover the chat.
  const nonModal = kind === "activity";
  const presentation = !shown
    ? null
    : beside
      ? "beside"
      : kind === "view"
        ? "cover"
        : nonModal
          ? "sheet-over"
          : "sheet";
  const shownAs = useRef(presentation);
  useEffect(() => {
    const before = shownAs.current;
    shownAs.current = presentation;
    if (!before || !presentation || before === presentation || presentation === "sheet") return;
    const target = presentation === "sheet-over" ? sheetPanel.current : aside.current;
    const active = document.activeElement;
    if (!target || target.contains(active)) return;
    // The view's frame (an iframe in its message) is laid over the cover.
    const hidden = presentation === "cover" && !(active instanceof HTMLIFrameElement);
    const lost = focusInPanel.current && (active === null || active === document.body);
    if (hidden || lost) target.focus();
  }, [presentation]);

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
    <div ref={region} className="relative flex min-h-0 min-w-0 flex-1">
      {/* No stacking context of its own: a view's frame lives in a message here
          and is laid out over the panel, so it must be able to paint above it. */}
      <div className="relative flex min-h-0 min-w-0 flex-1 flex-col">
        {launcher}
        {typeof children === "function"
          ? children({ sheetOver: presentation === "sheet-over" && !layout?.hidden })
          : children}
      </div>
      {shown && beside && (
        <>
          <div
            {...separatorProps}
            aria-label={t("file_preview_resize_handle")}
            style={{ width: HANDLE_WIDTH }}
            className="hover:bg-ax-border-strong focus-visible:outline-ring bg-ax-border shrink-0 cursor-col-resize touch-none focus-visible:outline-2"
          />
          <aside
            ref={aside}
            id={panelId}
            aria-label={label}
            tabIndex={-1}
            style={maximised ? undefined : { width }}
            className={cn(
              "bg-ax-surface flex min-h-0 shrink-0 flex-col focus-visible:outline-none",
              maximised ? "absolute inset-0 z-20" : "relative h-full"
            )}
          >
            {body(false)}
          </aside>
        </>
      )}
      {shown && !beside && !layout?.hidden && kind === "view" && (
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
      {shown && !beside && !layout?.hidden && kind !== "view" && (
        <BottomSheet
          // A modal and a non-modal sheet are different dialogs (showModal, show).
          key={nonModal ? "non-modal" : "modal"}
          ref={sheetPanel}
          isOpen
          onOpenChange={(open) => {
            if (!open) close();
          }}
          label={label}
          height={nonModal ? "capped" : "tall"}
          hasScrim={!nonModal}
        >
          {/* pt clears the sheet's grab handle, which floats over its top. */}
          <div id={panelId} className="flex h-full min-h-0 flex-col pt-3">
            {body(true)}
          </div>
        </BottomSheet>
      )}
    </div>
  );
}
