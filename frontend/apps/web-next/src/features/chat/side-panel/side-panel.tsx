"use client";

import { BottomSheet } from "@astryxdesign/core/BottomSheet";
import { useMediaQuery } from "@astryxdesign/core/hooks";
import { IconButton } from "@astryxdesign/core/IconButton";
import { Activity, PanelRightClose, PanelRightOpen } from "lucide-react";
import { useTranslations } from "next-intl";
import { useEffect, useEffectEvent, useId, useRef, type ReactNode } from "react";
import { findAppCall } from "@/features/mcp-apps/mcp-apps";
import type { PreviewFile } from "@/features/workspace/preview/preview-kind";
import type { EneoUIMessage } from "@/lib/chat/types";
import { useResizableSplit } from "@/lib/hooks/use-resizable-split";
import { cn } from "@/lib/utils";
import type { DocumentExport } from "./document-export";
import { FilePanel } from "./file-panel";
import type { PanelContents } from "./panel-contents";
import { panelContentsCount } from "./panel-contents";
import { PanelContentsList, type ActivityEntry } from "./panel-contents-list";
import {
  PanelFrame,
  type PanelHeadingLevel,
  type PanelMaximise,
  type PanelSwitcher
} from "./panel-frame";
import type { SidePanelStore } from "./side-panel-store";
import { ViewPanel } from "./view-panel";

export const SIDE_PANEL_ID = "chat-side-panel";

/** The panel beside the conversation: its width is the reader's. */
const PANEL_SPLIT = {
  storageKey: "eneo:chat-side-panel-width",
  defaultWidth: 520,
  minWidth: 360,
  maxFraction: 0.65
};
/** The conversation beside the panel, where the panel is the page's main column. */
const COMPANION_SPLIT = {
  storageKey: "eneo:chat-companion-width",
  defaultWidth: 420,
  minWidth: 320,
  maxFraction: 0.5
};

/** The activity of an answer, shown by the chat view as the panel's occupant when nothing else is. */
export type ActivityOccupant = {
  /** The tabs and steps (ActivityPanelBody), rendered inside the frame. */
  body: ReactNode;
  detail: string;
  onClose: () => void;
};

/** What the frame hands an occupant that draws its own PanelFrame. */
export type OccupantFrame = {
  switcher: PanelSwitcher | null;
  maximise: PanelMaximise | null;
  /** The panel is the page's main column: the occupant is the page, not a panel over it. */
  primary: boolean;
  headingLevel: PanelHeadingLevel;
};

/**
 * The page's own content beside the conversation (a flow page's panel),
 * rendered in the frame whenever the store's occupant is `native`.
 */
export type NativeOccupant = {
  /** The region's accessible name. */
  label: string;
  /** Renders the occupant, frame parts included (it draws its own PanelFrame). */
  body: (frame: OccupantFrame) => ReactNode;
};

/**
 * The conversation as the companion of the page's own content: from 1024px
 * the panel is the main column and the conversation a column beside it,
 * with this header and a button that folds it away.
 */
export type ConversationCompanion = {
  /** The conversation column's accessible name. */
  label: string;
  /** Who the reader talks to, as the chat header shows it. */
  identity: ReactNode;
  /** The page's menu, at the end of the header. */
  menu?: ReactNode;
};

export type SidePanelProps = {
  panel: SidePanelStore;
  messages: readonly EneoUIMessage[];
  contents: PanelContents;
  versionsOf: (file: PreviewFile) => PreviewFile[];
  exportOf: (file: PreviewFile) => DocumentExport | null;
  /** Native content for the `native` occupant; null on pages without any. */
  native?: NativeOccupant | null;
  /** Set where the native content is the page and the conversation its companion. */
  companion?: ConversationCompanion | null;
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
 *
 * With a `companion` the roles are swapped from 1024px: the panel is the
 * page's main column (its native content the default occupant, closing a
 * file or view returns to it) and the conversation a resizable column at
 * the end that the reader can fold away. Below 1024px nothing changes.
 */
export function SidePanel({
  panel,
  messages,
  contents,
  versionsOf,
  exportOf,
  native = null,
  companion = null,
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

  // The panel is the page's main column and the conversation its companion.
  const primary = companion !== null && native !== null && beside;
  const occupant = panel.occupant;
  const kind =
    occupant.kind !== "closed"
      ? occupant.kind
      : activity
        ? "activity"
        : primary
          ? "native"
          : "closed";
  const shownView = occupant.kind === "view" ? findAppCall(messages, occupant.callId) : null;
  const hasContents = panelContentsCount(contents) > 0;
  const shown =
    kind !== "closed" && !(kind === "overview" && !hasContents) && !(kind === "native" && !native);
  const maximised =
    !primary && panel.maximised && (kind === "file" || kind === "view" || kind === "native");
  const collapsed = primary && panel.conversationCollapsed;
  const { width, containerRef, separatorProps } = useResizableSplit({
    ...(companion ? COMPANION_SPLIT : PANEL_SPLIT),
    enabled: shown && beside && !collapsed
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
  const wasKind = useRef(kind);
  useEffect(() => {
    const landsHere = kind === "file" || kind === "overview";
    // As the main column the panel is always shown: what arrives is a new occupant.
    const arrived = primary ? wasKind.current !== kind : shown && !wasShown.current;
    if (arrived && landsHere && !panel.openedByItself && beside) {
      aside.current?.focus();
    }
    if (!shown && wasShown.current && document.activeElement === document.body) {
      trigger.current?.focus();
    }
    wasShown.current = shown;
    wasKind.current = kind;
  }, [shown, kind, beside, primary, panel.openedByItself]);

  const close = () => {
    if (occupant.kind === "view") panel.dismissView();
    else if (occupant.kind === "file") panel.close();
    else if (occupant.kind === "native") panel.closeNative();
    else if (occupant.kind === "overview") panel.closeOverview();
    else activity?.onClose();
  };

  // Escape steps back: out of the maximised panel first, then out of the
  // panel. The page's own content is not left by Escape.
  const onEscape = useEffectEvent(() => {
    if (primary && kind === "native") return;
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

  const conversationId = `${panelId}-conversation`;
  // A view's frame stays in its message, so folding the conversation away
  // would take the view with it: the toggle waits until the view closes.
  const maximise: PanelMaximise | null = primary
    ? kind === "view"
      ? null
      : {
          on: collapsed,
          toggle: () => panel.setConversationCollapsed(!collapsed),
          kind: "companion",
          controls: conversationId
        }
    : beside && (kind === "file" || kind === "view" || kind === "native")
      ? { on: panel.maximised, toggle: () => panel.setMaximised(!panel.maximised), kind: "cover" }
      : null;
  const headingLevel: PanelHeadingLevel = primary ? 1 : 2;

  const body = (narrow: boolean) => {
    switch (kind) {
      case "file":
        return (
          <FilePanel
            panel={panel}
            versionsOf={versionsOf}
            exportOf={exportOf}
            switcher={switcher}
            maximise={maximise}
            narrow={narrow}
            headingLevel={headingLevel}
          />
        );
      case "view":
        return shownView ? (
          <ViewPanel
            panel={panel}
            call={shownView.call}
            switcher={switcher}
            maximise={maximise}
            headingLevel={headingLevel}
          />
        ) : null;
      case "native":
        return native ? native.body({ switcher, maximise, primary, headingLevel }) : null;
      case "overview":
        return (
          <PanelFrame
            icon={<PanelRightOpen className="size-4" />}
            tileClassName="bg-ax-muted text-ax-text-secondary"
            title={t("conversation_panel_title")}
            switcher={null}
            maximise={primary ? maximise : null}
            onClose={() => panel.closeOverview()}
            closeLabel={t("conversation_panel_close")}
            headingLevel={headingLevel}
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
            maximise={primary ? maximise : null}
            onClose={activity.onClose}
            closeLabel={t("chat_activity_close")}
            headingLevel={headingLevel}
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
          : kind === "native" && native
            ? native.label
            : t("conversation_panel_title");

  if (primary && companion) {
    return (
      <div ref={containerRef} className="relative flex min-h-0 min-w-0 flex-1">
        <aside
          ref={aside}
          id={panelId}
          aria-label={label}
          tabIndex={-1}
          className="bg-ax-surface relative flex h-full min-h-0 min-w-0 flex-1 flex-col focus-visible:outline-none"
        >
          {body(false)}
        </aside>
        {!collapsed && (
          <div
            {...separatorProps}
            aria-label={t("chat_companion_resize_handle")}
            className="hover:bg-ax-border-strong focus-visible:outline-ring bg-ax-border w-1 shrink-0 cursor-col-resize touch-none focus-visible:outline-2"
          />
        )}
        {/* Folded away, not unmounted: the conversation keeps what is typed
            and streamed, and a view's frame stays in its message. */}
        <section
          id={conversationId}
          aria-label={companion.label}
          hidden={collapsed}
          style={collapsed ? undefined : { width }}
          className="relative flex min-h-0 shrink-0 flex-col"
        >
          <header className="border-ax-border flex min-h-14 shrink-0 items-center gap-2 border-b ps-2.5 pe-2.5">
            {companion.identity}
            <span className="flex-1" />
            {companion.menu}
            <IconButton
              label={t("chat_companion_hide")}
              tooltip={t("chat_companion_hide")}
              icon={<PanelRightClose className="size-[18px]" />}
              variant="ghost"
              onClick={() => {
                // The button goes with the column; the page's content takes the focus.
                panel.setConversationCollapsed(true);
                aside.current?.focus();
              }}
            />
          </header>
          {children}
        </section>
      </div>
    );
  }

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
    <div ref={containerRef} className="relative flex min-h-0 min-w-0 flex-1">
      {/* No stacking context of its own: a view's frame lives in a message here
          and is laid out over the panel, so it must be able to paint above it. */}
      <div className="relative flex min-h-0 min-w-0 flex-1 flex-col">
        {launcher}
        {children}
      </div>
      {shown && beside && (
        <>
          <div
            {...separatorProps}
            aria-label={t("file_preview_resize_handle")}
            className="hover:bg-ax-border-strong focus-visible:outline-ring bg-ax-border w-1 shrink-0 cursor-col-resize touch-none focus-visible:outline-2"
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
        >
          <div id={panelId} className="flex h-full min-h-0 flex-col">
            {body(true)}
          </div>
        </BottomSheet>
      )}
    </div>
  );
}
