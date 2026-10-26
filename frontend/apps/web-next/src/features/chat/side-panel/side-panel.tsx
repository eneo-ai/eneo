"use client";

import { BottomSheet } from "@astryxdesign/core/BottomSheet";
import { useMediaQuery } from "@astryxdesign/core/hooks";
import { ResizeHandle, useResizable } from "@astryxdesign/core/Resizable";
import { Activity, FileText, PanelRightOpen } from "lucide-react";
import { useTranslations } from "next-intl";
import {
  Component,
  lazy,
  useCallback,
  Suspense,
  useEffect,
  useEffectEvent,
  useId,
  useLayoutEffect,
  useRef,
  useState,
  type ReactNode
} from "react";
import { ListError } from "@/components/composites/query-state";
import { useFocusRescue } from "@/lib/focus-rescue";
import { findAppCall } from "@/features/mcp-apps/mcp-apps";
import type { PreviewFile } from "@/features/workspace/preview/preview-kind";
import type { EneoUIMessage } from "@/lib/chat/types";
import { useElementWidth } from "@/lib/hooks/use-element-width";
import { cn } from "@/lib/utils";
import type { DocumentExport } from "./document-export";
import type { DocumentSaver } from "./document-saver";
import type { PanelContents } from "./panel-contents";
import { panelContentsCount } from "./panel-contents";
import { PanelContentsList, type ActivityEntry } from "./panel-contents-list";
import { PanelFrame, type PanelMaximise, type PanelSwitcher } from "./panel-frame";
import type { SidePanelStore } from "./side-panel-store";
import { ViewPanel } from "./view-panel";

// The file panel carries the document editor (TipTap, ProseMirror, highlighting)
// and the previews. It loads once the conversation is idle, not with the page.
let filePanelModule: typeof import("./file-panel") | null = null;
const loadFilePanel = () => import("./file-panel").then((module) => (filePanelModule = module));
// React keeps a lazy component's failed load, so a retry needs a new one. Once
// the code is here (the idle prefetch), the panel resolves at once: a pending
// load would show the loading frame for React's 300 ms reveal throttle.
const lazyFilePanel = () =>
  lazy(() => {
    if (filePanelModule === null) {
      return loadFilePanel().then((module) => ({ default: module.FilePanel }));
    }
    const ready = { default: filePanelModule.FilePanel };
    // React's lazy takes any thenable (its types say Promise); one that
    // resolves synchronously renders without suspending.
    return {
      then: (resolve: (value: typeof ready) => void) => resolve(ready)
    } as unknown as Promise<typeof ready>;
  });

/**
 * Marks a loading or failed frame as shown, for as long as it is: it is
 * swapped for the next one, taking any control the reader had focused with it.
 */
function TemporaryFrame({ onShown }: { onShown: (shown: boolean) => void }) {
  useLayoutEffect(() => {
    onShown(true);
    return () => onShown(false);
  }, [onShown]);
  return null;
}

/**
 * Keeps a failed file panel (its code gone after a deploy, a dropped
 * connection) inside the panel with a retry, so the conversation stays usable.
 */
class FilePanelBoundary extends Component<
  { frame: (body: ReactNode) => ReactNode; onRetry: () => void; children: ReactNode },
  { failure: { error: unknown } | null }
> {
  override state: { failure: { error: unknown } | null } = { failure: null };

  static getDerivedStateFromError(error: unknown) {
    return { failure: { error } };
  }

  override render() {
    const { failure } = this.state;
    if (failure === null) return this.props.children;
    return this.props.frame(
      <div className="p-4">
        <ListError
          error={failure.error}
          onRetry={() => {
            this.props.onRetry();
            this.setState({ failure: null });
          }}
        />
      </div>
    );
  }
}

export const SIDE_PANEL_ID = "chat-side-panel";
const WIDTH_STORAGE_KEY = "eneo:chat-side-panel-width";

/**
 * How the panel is laid out: beside the conversation, over it in the same
 * region, or as a sheet over the whole viewport (a view: a fixed cover).
 */
export type SidePanelMode = "beside" | "over" | "sheet";

/**
 * The narrowest region the panel shares with the conversation. Beside it the
 * panel is at least 360px (its minSize), and the conversation needs about as
 * much; narrower than that, two halves are each too small to use.
 */
export const BESIDE_MIN_WIDTH = 720;

/**
 * Which layout the panel gets. The window decides whether a sheet is called
 * for (tablets, phones, 200 to 400% zoom); from 1024px the region the chat
 * has decides between beside and over, since a chat in a column of a page
 * (the flow page's) is far narrower than the window. An unmeasured region
 * (not laid out yet) is taken as wide, so the panel does not start out over
 * the conversation and then jump beside it.
 */
export function sidePanelMode(wideWindow: boolean, regionWidth: number | null): SidePanelMode {
  if (!wideWindow) return "sheet";
  return regionWidth !== null && regionWidth < BESIDE_MIN_WIDTH ? "over" : "beside";
}

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
 * show. Beside the conversation when the region is wide enough for both, with
 * a handle to resize it and a maximise over the conversation; over the
 * conversation in a narrow region of a wide window (the chat column of the
 * flow page), where the frame's close button is the way back; below 1024px a
 * BottomSheet, except a view, whose frame stays mounted in the message and is
 * laid out over a cover.
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
  const wideWindow = useMediaQuery("(min-width: 1024px)");
  // The row the conversation and the panel share, measured for the mode.
  const [measureRow, rowWidth] = useElementWidth<HTMLDivElement>();
  const mode = sidePanelMode(wideWindow, rowWidth);
  const beside = mode === "beside";
  const aside = useRef<HTMLElement>(null);
  const trigger = useRef<HTMLButtonElement>(null);
  const fileArea = useRef<HTMLDivElement>(null);
  // A loading or failed frame is swapped for the next one, taking any control
  // the reader had focused with it. Whether the reader's focus is in it is
  // tracked while it is shown; when it goes with focus in it, focus is rescued
  // into the file's area, not left on the page.
  const temporaryFrame = useRef(false);
  const focusInTemporaryFrame = useRef(false);
  const rescueFocus = useFocusRescue();
  const markTemporaryFrame = useCallback(
    (shown: boolean) => {
      temporaryFrame.current = shown;
      if (shown || !focusInTemporaryFrame.current) return;
      focusInTemporaryFrame.current = false;
      rescueFocus(() => fileArea.current);
    },
    [rescueFocus]
  );

  // Over the conversation the panel hides it, as a sheet does: it must not
  // open by itself there, and a quote returns to the composer.
  useEffect(() => {
    panel.setBesideConversation(beside);
  }, [panel, beside]);

  const [FilePanel, setFilePanel] = useState(lazyFilePanel);
  useEffect(() => {
    const idle = window.requestIdleCallback ?? ((load: () => void) => setTimeout(load, 1));
    const cancel = window.cancelIdleCallback ?? clearTimeout;
    // Only a head start: opening a file loads the panel itself and reports a failure.
    const handle = idle(() => void loadFilePanel().catch(() => {}));
    return () => cancel(handle);
  }, []);

  const occupant = panel.occupant;
  const kind = occupant.kind !== "closed" ? occupant.kind : activity ? "activity" : "closed";
  const shownView = occupant.kind === "view" ? findAppCall(messages, occupant.callId) : null;
  const hasContents = panelContentsCount(contents) > 0;
  const shown = kind !== "closed" && !(kind === "overview" && !hasContents);
  const maximised = beside && panel.maximised && (kind === "file" || kind === "view");
  // Whether the panel takes the whole row, with the conversation under it.
  const covering = maximised || mode === "over";
  // The panel's width, a share of the row both halves share. The row is the
  // basis only while the panel is beside the conversation: a narrower row
  // (phone-wide, or a column of a page) would clamp the remembered width
  // down and lose it.
  const containerRef = useRef<HTMLDivElement>(null);
  const row = useCallback(
    (element: HTMLDivElement | null) => {
      measureRow(element);
      containerRef.current = beside ? element : null;
    },
    [measureRow, beside]
  );
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
  // focuses its own tab. The sheet is a dialog and places focus itself.
  // Closing hands focus back to the opener (the store does that for files),
  // or to the panel button.
  const wasShown = useRef(false);
  useEffect(() => {
    const landsHere = kind === "file" || kind === "overview";
    if (shown && !wasShown.current && landsHere && !panel.openedByItself && mode !== "sheet") {
      aside.current?.focus();
    }
    if (!shown && wasShown.current && document.activeElement === document.body) {
      trigger.current?.focus();
    }
    wasShown.current = shown;
  }, [shown, kind, mode, panel.openedByItself]);

  // Focus is in the temporary frame from when it enters until it moves to
  // something outside the file's area or the reader presses outside it. A
  // removed control gives no outside target, so its loss keeps the mark.
  useEffect(() => {
    const area = fileArea.current;
    if (!area) return;
    const onFocusIn = () => {
      if (temporaryFrame.current) focusInTemporaryFrame.current = true;
    };
    const onFocusOut = (event: FocusEvent) => {
      if (event.relatedTarget instanceof Node && !area.contains(event.relatedTarget)) {
        focusInTemporaryFrame.current = false;
      }
    };
    const onPointerDown = (event: PointerEvent) => {
      if (!(event.target instanceof Node && area.contains(event.target))) {
        focusInTemporaryFrame.current = false;
      }
    };
    area.addEventListener("focusin", onFocusIn);
    area.addEventListener("focusout", onFocusOut);
    document.addEventListener("pointerdown", onPointerDown, true);
    return () => {
      area.removeEventListener("focusin", onFocusIn);
      area.removeEventListener("focusout", onFocusOut);
      document.removeEventListener("pointerdown", onPointerDown, true);
    };
  }, [kind, shown, beside]);

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
  }, [shown, mode, kind]);

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
      case "file": {
        // While the panel's code loads or after it failed to: the file's frame,
        // so the panel can still be closed or switched.
        const frame = (content: ReactNode) => (
          <PanelFrame
            icon={<FileText className="size-4" />}
            title={panel.file?.name ?? t("conversation_panel_title")}
            switcher={switcher}
            maximise={maximise}
            onClose={() => panel.close()}
          >
            <TemporaryFrame onShown={markTemporaryFrame} />
            {content}
          </PanelFrame>
        );
        return (
          <div
            ref={fileArea}
            tabIndex={-1}
            className="flex min-h-0 flex-1 flex-col focus-visible:outline-none"
          >
            <FilePanelBoundary frame={frame} onRetry={() => setFilePanel(lazyFilePanel)}>
              <Suspense
                fallback={frame(
                  <p className="text-ax-text-secondary p-6 text-sm">{t("file_preview_loading")}</p>
                )}
              >
                <FilePanel
                  panel={panel}
                  versionsOf={versionsOf}
                  exportOf={exportOf}
                  saverOf={saverOf}
                  switcher={switcher}
                  maximise={maximise}
                  narrow={narrow}
                />
              </Suspense>
            </FilePanelBoundary>
          </div>
        );
      }
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
    <div ref={row} className="relative flex min-h-0 min-w-0 flex-1">
      {/* No stacking context of its own: a view's frame lives in a message here
          and is laid out over the panel, so it must be able to paint above it. */}
      <div className="relative flex min-h-0 min-w-0 flex-1 flex-col">
        {launcher}
        {children}
      </div>
      {shown && mode !== "sheet" && (
        <>
          {/* The panel sits at the end of the row: dragging the handle left widens it. */}
          {beside && (
            <ResizeHandle
              isReversed
              hasDivider
              label={t("file_preview_resize_handle")}
              resizable={resizable.props}
            />
          )}
          {/* The same element beside and over: a row resized across the
              threshold keeps the panel, and the focus in it. */}
          <aside
            ref={aside}
            id={panelId}
            aria-label={label}
            tabIndex={-1}
            style={covering ? undefined : { width: resizable.size }}
            className={cn(
              "bg-ax-surface flex min-h-0 shrink-0 flex-col focus-visible:outline-none",
              covering ? "absolute inset-0 z-20" : "relative h-full"
            )}
          >
            {body(mode === "over")}
          </aside>
        </>
      )}
      {shown && mode === "sheet" && kind === "view" && (
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
      {shown && mode === "sheet" && kind !== "view" && (
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
