"use client";

import { AlertDialog } from "@astryxdesign/core/AlertDialog";
import { Button } from "@astryxdesign/core/Button";
import { Skeleton } from "@astryxdesign/core/Skeleton";
import { useQueryClient } from "@tanstack/react-query";
import { useTheme } from "next-themes";
import { useLocale, useTranslations } from "next-intl";
import { useCallback, useEffect, useRef, useState } from "react";
import { useSidePanel } from "@/features/chat/side-panel/use-side-panel";
import { useAutomaticConversationTools } from "@/features/chat/conversation-settings";
import { cn } from "@/lib/utils";
import { McpAppBridge, type McpAppToolResult, type McpAppToolState } from "./bridge";
import { hostContext } from "./host-context";
import {
  appViewSubject,
  appViewTitle,
  buildAllowAttribute,
  hasResult,
  type McpAppCall,
  type McpAppDisplayMode
} from "./mcp-apps";
import { useViewLink } from "./use-view-link";
import { callToolFromView, toolCallOutcome } from "./view-tool-calls";

// A view takes the room it asks for. One shown with the answer being written
// starts with none, so a view with nothing to show never flickers into the
// answer; an earlier answer's view holds its place until it loads.
const UNSIZED_HEIGHT = 320;
const SIZE_WAIT_MS = 1500;
const ARGUMENTS_PREVIEW_LENGTH = 400;

type Rect = { top: number; left: number; width: number; height: number };

/** The place of the panel's frame anchor in the viewport, followed as it moves. */
function useAnchorRect(target: HTMLElement | null): Rect | null {
  const [rect, setRect] = useState<Rect | null>(null);
  useEffect(() => {
    if (!target) return;
    const measure = () => {
      const { top, left, width, height } = target.getBoundingClientRect();
      setRect({ top, left, width, height });
    };
    // Observing reports the anchor's size once at the start, which measures it.
    const observer = new ResizeObserver(measure);
    observer.observe(target);
    window.addEventListener("resize", measure);
    window.addEventListener("scroll", measure, true);
    return () => {
      observer.disconnect();
      window.removeEventListener("resize", measure);
      window.removeEventListener("scroll", measure, true);
    };
  }, [target]);
  // A measurement belongs to the anchor it was taken over; without one there is no place.
  return target ? rect : null;
}

type Decision<T> = { payload: T; decide: (allow: boolean) => void };

/**
 * An approved interactive view (MCP App) under its answer: the server's HTML
 * in a sandboxed frame on the content origin, bridged with the official SDK.
 * The frame stays mounted in the message for its whole life; when the view is
 * shown beside the conversation the same frame is laid out over the panel's
 * anchor, so filters, loaded rows and the SDK connection survive the move.
 */
export function McpAppFrame({
  call,
  live,
  sessionId
}: {
  call: McpAppCall;
  /** The call belongs to the answer being written right now. */
  live: boolean;
  sessionId: string | null;
}) {
  const t = useTranslations();
  const locale = useLocale();
  const queryClient = useQueryClient();
  const panel = useSidePanel();
  const { link, error } = useViewLink(call.view.viewId);
  const { resolvedTheme } = useTheme();

  const movedToPane = panel?.viewCallId === call.toolCallId;
  const displayMode: McpAppDisplayMode = movedToPane ? "fullscreen" : "inline";
  const panelRect = useAnchorRect(movedToPane ? (panel?.viewTarget ?? null) : null);

  const frameRef = useRef<HTMLIFrameElement | null>(null);
  const bridgeRef = useRef<McpAppBridge | null>(null);
  const loadedFrame = useRef<HTMLIFrameElement | null>(null);
  const sized = useRef(false);
  const [frameHeight, setFrameHeight] = useState(live ? 0 : UNSIZED_HEIGHT);
  const [enlargeable, setEnlargeable] = useState(false);
  const [leftApprovedView, setLeftApprovedView] = useState(false);
  const [asking, setAsking] = useState<Decision<{ name: string; args: unknown }> | null>(null);
  const [link_, setLink] = useState<Decision<string> | null>(null);
  // Fixed for the frame's lifetime: the attribute only matters before the
  // first load, and Firefox reloads a frame whose `loading` changes to lazy,
  // which would read as the view having navigated away.
  const [loading] = useState<"eager" | "lazy">(live ? "eager" : "lazy");

  // The bridge's callbacks read the newest props and store through this ref,
  // written after every commit.
  const automaticTools = useAutomaticConversationTools();
  const latest = useRef({ call, live, panel, sessionId, displayMode, locale, automaticTools });
  useEffect(() => {
    latest.current = { call, live, panel, sessionId, displayMode, locale, automaticTools };
  });

  // What the view is told about its call: the arguments while the model
  // writes them, the finished arguments, and that the tool has returned.
  const tool: McpAppToolState = {
    partialInput: call.state === "input-streaming" ? call.input : undefined,
    input: call.state === "input-streaming" ? undefined : (call.input ?? {}),
    resultReady: hasResult(call, live)
  };
  useEffect(() => {
    bridgeRef.current?.update(tool);
    // The state is rebuilt on every render; its parts are what matters.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [call.state, call.input, tool.resultReady]);

  useEffect(() => {
    bridgeRef.current?.setDisplayMode(displayMode);
  }, [displayMode]);

  // A view shown in Eneo's colours follows them when the theme changes.
  useEffect(() => {
    bridgeRef.current?.contextChanged();
  }, [resolvedTheme]);

  // Such a view, once it has something to show, is offered in the panel's
  // switcher, so the reader can bring it there without finding it in the chat.
  const offered = Boolean(panel) && enlargeable && frameHeight > 0;
  useEffect(() => {
    if (!panel || !offered) return;
    panel.offerView(call.toolCallId, true);
    return () => panel.offerView(call.toolCallId, false);
  }, [panel, offered, call.toolCallId]);

  const requestDisplayMode = useCallback((mode: McpAppDisplayMode): McpAppDisplayMode => {
    const { panel, displayMode, live, call } = latest.current;
    if (!panel || mode === displayMode) return displayMode;
    // A view moves on the user's action in it. One that is merely on screen
    // cannot take the panel, except the view of the answer being written,
    // which may open it once unless the user has closed it during this answer.
    const acted = document.activeElement === frameRef.current;
    const opensWithItsAnswer = live && mode === "fullscreen" && !panel.viewDismissedThisAnswer;
    if (!acted && !opensWithItsAnswer) return displayMode;
    // Change only layout. The iframe and its SDK connection stay mounted.
    if (mode === "fullscreen") panel.openView(call.toolCallId);
    else panel.closeView();
    return mode;
  }, []);

  // A link is opened only when the reader, shown the whole address, says so.
  const openLink = useCallback(
    (url: string) =>
      new Promise<boolean>((resolve) => {
        setLink((current) => {
          if (current) {
            resolve(false);
            return current;
          }
          return {
            payload: url,
            decide: (open) => {
              setLink(null);
              if (open) window.open(url, "_blank", "noopener,noreferrer");
              resolve(open);
            }
          };
        });
      }),
    []
  );

  // Only on the reader's action in the view: a view that is merely on screen
  // cannot write into the message box.
  const offerMessage = useCallback((text: string): boolean => {
    const { panel } = latest.current;
    if (!panel || document.activeElement !== frameRef.current) return false;
    panel.suggestMessage(text);
    return true;
  }, []);

  // What the view says the reader has selected in it is quoted in the next
  // question, shown above the message box like a quote from a file.
  const quoteContext = useCallback(
    (text: string): boolean => {
      const { panel, call } = latest.current;
      if (!panel) return false;
      // Like a message, text is taken only on the reader's action in the view.
      // Withdrawing its own quote is always the view's to do.
      if (text !== "" && document.activeElement !== frameRef.current) return false;
      panel.quoteView(call.toolCallId, appViewSubject(call) ?? appViewTitle(call, t), text);
      return true;
    },
    [t]
  );

  // External code gets consent for each concrete call, never a server-wide
  // grant inherited from the model's automatic-tool preference.
  const permissionToRunTools = useCallback(
    (name: string, args: Record<string, unknown>) =>
      new Promise<boolean>((resolve) => {
        if (latest.current.call.isBundled && latest.current.automaticTools) return resolve(true);
        setAsking((current) => {
          // Concurrent requests cannot share the approval of another call.
          if (current) {
            resolve(false);
            return current;
          }
          return {
            payload: { name, args },
            decide: (allow) => {
              setAsking(null);
              resolve(allow);
            }
          };
        });
      }),
    []
  );

  const callTool = useCallback(
    async (name: string, args: Record<string, unknown>): Promise<McpAppToolResult> => {
      if (!(await permissionToRunTools(name, args))) {
        throw new Error("The user did not allow the tool call");
      }
      const { sessionId, call } = latest.current;
      if (!sessionId) throw new Error("The conversation is not saved yet");
      const result = await callToolFromView({
        sessionId,
        toolCallId: call.toolCallId,
        viewId: call.view.viewId,
        name,
        arguments: args
      });
      return {
        content: (result.content ?? []).map((block) => ({ type: "text", text: block.text })),
        ...(result.structured_content ? { structuredContent: result.structured_content } : {}),
        ...(result.is_error ? { isError: true } : {})
      };
    },
    [permissionToRunTools]
  );

  // The frame that has loaded the approved view. A frame can navigate itself
  // (a link in the view is enough) and would then hold a page nobody approved
  // in the same window; such a page is never given the bridge.
  const attachBridge = (iframe: HTMLIFrameElement) => {
    bridgeRef.current?.destroy();
    setEnlargeable(false);
    if (loadedFrame.current === iframe) {
      bridgeRef.current = null;
      setLeftApprovedView(true);
      console.warn(`MCP app view ${call.view.viewId} loaded a second time; it is no longer shown`);
      return;
    }
    loadedFrame.current = iframe;
    const bridge = new McpAppBridge({
      iframe,
      html: link?.html ?? "",
      permissions: call.view.ui.permissions?.clipboardWrite ? { clipboardWrite: {} } : undefined,
      displayMode: latest.current.displayMode,
      getToolResult: () => {
        const { sessionId, call } = latest.current;
        return sessionId
          ? toolCallOutcome(queryClient, sessionId, call.toolCallId)
          : Promise.resolve(null);
      },
      onSizeChanged: (height) => {
        sized.current = true;
        setFrameHeight(height);
      },
      onInitialized: (displayModes) => setEnlargeable(displayModes.includes("fullscreen")),
      onRequestDisplayMode: panel ? requestDisplayMode : undefined,
      onCallTool: callTool,
      onOpenLink: openLink,
      onMessage: offerMessage,
      onModelContext: quoteContext,
      hostContext: () => hostContext(latest.current.locale)
    });
    bridgeRef.current = bridge;
    bridge.update(tool);
    // A view that never says its size is given room all the same.
    setTimeout(() => {
      if (!sized.current && bridgeRef.current === bridge) setFrameHeight(UNSIZED_HEIGHT);
    }, SIZE_WAIT_MS);
  };

  useEffect(
    () => () => {
      bridgeRef.current?.destroy();
      bridgeRef.current = null;
    },
    []
  );

  const title = appViewTitle(call, t);
  // SDK sizes describe the app viewport; the border is drawn outside it.
  const bordered = frameHeight > 0 && call.view.ui.prefersBorder !== false;
  const frameStyle = movedToPane
    ? panelRect
      ? {
          position: "fixed" as const,
          zIndex: 30,
          top: panelRect.top,
          left: panelRect.left,
          width: panelRect.width,
          height: panelRect.height
        }
      : { visibility: "hidden" as const, position: "fixed" as const }
    : frameHeight === 0
      ? // Keep the bridge measurable and connected without adding a flex gap.
        { position: "absolute" as const, height: 0, overflow: "hidden" }
      : { height: frameHeight + (bordered ? 2 : 0) };

  const note = (text: string) => (
    <p
      role="note"
      className="border-ax-border-strong text-ax-text-secondary rounded-ax-container mt-2 border border-dashed px-3 py-2 text-xs"
    >
      {text}
    </p>
  );

  return (
    <>
      {movedToPane && (
        <div
          role="note"
          className="border-ax-border-strong text-ax-text-secondary rounded-ax-container mt-2 flex items-center justify-between gap-3 border border-dashed px-3 py-2 text-xs"
        >
          <span>{t("mcp_app_view_beside")}</span>
          <Button
            label={t("mcp_app_view_show_here")}
            variant="ghost"
            size="sm"
            onClick={() => panel?.closeView()}
          />
        </div>
      )}
      {leftApprovedView ? (
        note(t("mcp_app_view_left"))
      ) : error ? (
        note(
          error.contentOriginMissing
            ? t("mcp_app_view_unavailable")
            : t("mcp_app_view_unavailable_generic")
        )
      ) : !link ? (
        <div
          aria-hidden="true"
          className={cn(
            "rounded-ax-container mt-2 overflow-hidden",
            displayMode === "inline" && frameHeight === 0 && "hidden"
          )}
          style={displayMode === "inline" ? { height: frameHeight } : undefined}
        >
          <Skeleton radius={3} />
        </div>
      ) : (
        <iframe
          ref={frameRef}
          src={link.url}
          title={title}
          sandbox="allow-scripts allow-same-origin"
          allow={buildAllowAttribute(call.view.ui.permissions)}
          referrerPolicy="no-referrer"
          loading={loading}
          className={cn(
            displayMode === "inline"
              ? cn(
                  "rounded-ax-container w-full",
                  // A view with nothing to show takes no room, border and margin included.
                  frameHeight > 0 && "mt-2",
                  bordered && "border-ax-border shadow-ax-low border"
                )
              : "min-h-0 w-full flex-1",
            (asking || link_) && "invisible"
          )}
          style={frameStyle}
          onLoad={(event) => attachBridge(event.currentTarget)}
        />
      )}

      <AlertDialog
        isOpen={asking !== null}
        onOpenChange={(open) => {
          if (!open) asking?.decide(false);
        }}
        title={t("mcp_app_view_tool_permission_title")}
        description={`${t("mcp_app_view_tool_permission_description", {
          view: title,
          tool: asking?.payload.name ?? ""
        })} ${argumentsPreview(asking?.payload.args)}`}
        actionLabel={t("tool_accept")}
        actionVariant="primary"
        cancelLabel={t("tool_deny")}
        onAction={() => asking?.decide(true)}
      />
      <AlertDialog
        isOpen={link_ !== null}
        onOpenChange={(open) => {
          if (!open) link_?.decide(false);
        }}
        title={t("mcp_app_view_open_link_title")}
        description={`${t("mcp_app_view_open_link_description", { view: title })} ${link_?.payload ?? ""}`}
        actionLabel={t("mcp_app_view_open_link_confirm")}
        actionVariant="primary"
        cancelLabel={t("cancel")}
        onAction={() => link_?.decide(true)}
      />
    </>
  );
}

/** The arguments of a call the reader is asked to allow, cut to a readable length. */
function argumentsPreview(args: unknown): string {
  if (args === undefined) return "";
  const text = JSON.stringify(args);
  return text.length > ARGUMENTS_PREVIEW_LENGTH
    ? `${text.slice(0, ARGUMENTS_PREVIEW_LENGTH)}…`
    : text;
}
