"use client";

import { Button } from "@astryxdesign/core/Button";
import { Collapsible, CollapsibleGroup } from "@astryxdesign/core/Collapsible";
import { useClipboard } from "@astryxdesign/core/hooks";
import { Item } from "@astryxdesign/core/Item";
import { MetadataList, MetadataListItem } from "@astryxdesign/core/MetadataList";
import { ScrollableArea } from "@astryxdesign/core/ScrollableArea";
import { useQuery } from "@tanstack/react-query";
import { Ban, CircleCheck, CircleX, Clock, Copy, LoaderCircle, Square, Wrench } from "lucide-react";
import type { LucideIcon } from "lucide-react";
import { useLocale, useTranslations } from "next-intl";
import { browserApi } from "@/lib/api/browser";
import { unwrap } from "@/lib/api/errors";
import { cn } from "@/lib/utils";
import type { StepStatus, ToolCall, ToolPart } from "./activity";
import { callTimingKey, type TurnDurations } from "./activity-timings";
import { formatSeconds } from "./format";
import {
  fileIdFromUrl,
  toolPresentation,
  toolTarget,
  type AttachedFile
} from "./tool-presentation";

/**
 * The calls of one tool step in the Steg tab: a row per call (what it did,
 * what it did it to, how long it took) that opens to the arguments and the
 * result. The server is named once above the rows when the calls share it.
 */

const STATUS_KEY = {
  done: "chat_step_status_done",
  running: "chat_step_status_running",
  waiting: "chat_step_status_waiting",
  error: "chat_step_status_error",
  denied: "chat_step_status_denied",
  stopped: "chat_step_status_stopped"
} as const satisfies Record<StepStatus, string>;

const CALL_ICON: Record<StepStatus, { icon: LucideIcon; className: string; spin?: boolean }> = {
  done: { icon: CircleCheck, className: "text-ax-success" },
  running: { icon: LoaderCircle, className: "text-ax-text-accent", spin: true },
  waiting: { icon: Clock, className: "text-ax-text-secondary" },
  error: { icon: CircleX, className: "text-ax-error" },
  denied: { icon: Ban, className: "text-ax-warning" },
  stopped: { icon: Square, className: "text-ax-text-secondary" }
};

function CallStatusIcon({ status }: { status: StepStatus }) {
  const t = useTranslations();
  const { icon: Icon, className, spin } = CALL_ICON[status];
  return (
    <span className="flex size-4 items-center justify-center">
      <Icon
        aria-hidden="true"
        className={cn("size-3.5", className, spin && "animate-spin")}
        strokeWidth={2.2}
      />
      <span className="sr-only">{t(STATUS_KEY[status])}</span>
    </span>
  );
}

function callArguments(part: ToolPart): Record<string, unknown> {
  return part.input && typeof part.input === "object" && !Array.isArray(part.input)
    ? (part.input as Record<string, unknown>)
    : {};
}

/**
 * The arguments as a label/value list. A read of an attachment shows the
 * file's name and the position instead of its signed url; anything else
 * shows each argument, objects as JSON.
 */
function CallArguments({ part, files }: { part: ToolPart; files: AttachedFile[] }) {
  const t = useTranslations();
  const locale = useLocale();
  const args = callArguments(part);
  const entries = Object.entries(args);
  if (entries.length === 0) return null;

  const fileId = fileIdFromUrl(args.url);
  const file = fileId ? files.find((item) => item.id === fileId) : undefined;
  const rows = entries.map(([key, value]) => {
    if (key === "url" && file) {
      return { key, label: t("chat_tool_argument_file"), value: file.name };
    }
    if (key === "offset" && file && typeof value === "number") {
      return {
        key,
        label: t("from"),
        value:
          value > 0 ? new Intl.NumberFormat(locale).format(value) : t("chat_tool_argument_start")
      };
    }
    return {
      key,
      label: key,
      value: typeof value === "string" ? value : JSON.stringify(value, null, 2)
    };
  });

  return (
    <div className="flex flex-col gap-1">
      <p className="text-ax-text-secondary text-[11px] font-semibold">{t("chat_tool_arguments")}</p>
      {/* The panel's small type: the list's own labels are sized for a page. */}
      <div className="text-[12px] [&_.astryx-metadata-list-item]:text-[12px] [&_.astryx-metadata-list-item_*]:text-[12px]">
        <MetadataList label={{ position: "start", width: 64 }}>
          {rows.map((row) => (
            <MetadataListItem key={row.key} label={row.label}>
              <span className="text-[12px] break-words whitespace-pre-wrap">{row.value}</span>
            </MetadataListItem>
          ))}
        </MetadataList>
      </div>
    </div>
  );
}

/** The result, loaded when the row is open, in a scroll box with a copy button. */
function CallResult({ part, sessionId }: { part: ToolPart; sessionId: string | null }) {
  const t = useTranslations();
  const locale = useLocale();
  const { copy } = useClipboard({ announce: t("copied_to_clipboard") });
  const finished = part.state === "output-available" || part.state === "output-error";
  const canLoad = Boolean(sessionId && part.toolCallId && finished);
  const result = useQuery({
    queryKey: ["conversations", "tool-call-result", sessionId, part.toolCallId],
    enabled: canLoad,
    staleTime: Infinity,
    queryFn: async () => {
      const response = await unwrap(
        browserApi.GET("/api/v1/conversations/{session_id}/tool-calls/{tool_call_id}/result/", {
          params: { path: { session_id: sessionId!, tool_call_id: part.toolCallId } }
        })
      );
      return response.result ?? null;
    }
  });
  const errorText = part.state === "output-error" ? part.errorText : undefined;
  if (!canLoad) {
    return errorText ? <p className="text-ax-error text-[12.5px]">{errorText}</p> : null;
  }
  const text =
    typeof result.data === "string" && result.data.trim() ? result.data : (errorText ?? null);
  const body = result.isPending
    ? t("loading_ellipsis")
    : result.isError
      ? t("mcp_tool_response_load_error")
      : (text ?? t("mcp_tool_response_empty"));

  return (
    <div className="flex flex-col gap-1">
      <div className="flex min-h-6 items-center justify-between gap-2">
        <p className="text-ax-text-secondary text-[11px] font-semibold">{t("chat_tool_result")}</p>
        {text && (
          <Button
            label={t("copy")}
            isIconOnly
            variant="ghost"
            size="sm"
            icon={<Copy aria-hidden="true" className="size-3.5" />}
            onClick={() => void copy(text)}
          />
        )}
      </div>
      <ScrollableArea
        axis="block"
        label={t("chat_tool_result")}
        className="border-ax-border bg-ax-card rounded-ax-inner focus-visible:outline-ring max-h-40 border px-2.5 py-2 focus-visible:outline-2 focus-visible:-outline-offset-2"
      >
        <pre className="font-mono text-[11.5px] break-words whitespace-pre-wrap">{body}</pre>
      </ScrollableArea>
      {text && (
        <p className="text-ax-text-secondary text-[11.5px]">
          {t("chat_tool_result_length", {
            count: new Intl.NumberFormat(locale).format(text.length)
          })}
        </p>
      )}
    </div>
  );
}

export function ToolCallList({
  calls,
  files,
  sessionId,
  durations
}: {
  calls: ToolCall[];
  files: AttachedFile[];
  sessionId: string | null;
  durations: TurnDurations | null;
}) {
  const t = useTranslations();
  const locale = useLocale();
  const presented = calls.map((call) => ({
    call,
    presentation: toolPresentation(call.part, t, call.status === "done"),
    target: toolTarget(call.part, t, { files, locale })
  }));
  const servers = new Set(presented.map((item) => item.presentation.server));
  const sharedServer = servers.size === 1 ? (presented[0]?.presentation.server ?? null) : null;
  const serverLine = sharedServer ?? null;

  // The rows, with the label span fixes (its first child; the chevron is a
  // span too): it has no min-width, so a long description would push the
  // chevron out of the row instead of truncating.
  const rows = (
    <div className="px-1 [&_.astryx-collapsible-trigger]:min-h-9 [&_.astryx-collapsible-trigger>span:first-child]:min-w-0 [&_.astryx-collapsible-trigger>span:first-child]:flex-1 [&_.astryx-collapsible-trigger>span:first-child>*]:w-full">
      <CollapsibleGroup type="multiple" hasDividers density="compact">
        {presented.map(({ call, presentation, target }) => {
          const problem =
            call.status === "error"
              ? (call.part.errorText ?? t("chat_step_status_error"))
              : call.status === "denied" || call.status === "stopped"
                ? t(STATUS_KEY[call.status])
                : null;
          const description = [sharedServer ? null : presentation.server, problem ?? target]
            .filter(Boolean)
            .join(" · ");
          const duration = durations?.stepMs[callTimingKey(call.part.toolCallId)];
          return (
            <Collapsible
              key={call.part.toolCallId}
              value={call.part.toolCallId}
              defaultIsOpen={false}
              trigger={
                <Item
                  as="span"
                  density="compact"
                  align="start"
                  startContent={<CallStatusIcon status={call.status} />}
                  label={<span className="text-[13px]">{presentation.label}</span>}
                  description={
                    description ? (
                      <span className={cn("text-[12px]", problem && "text-ax-error")}>
                        {description}
                      </span>
                    ) : undefined
                  }
                  descriptionLines={1}
                  endContent={
                    duration !== undefined ? (
                      <span className="text-ax-text-secondary text-[11.5px] tabular-nums">
                        {formatSeconds(duration, locale)}
                      </span>
                    ) : undefined
                  }
                />
              }
            >
              <div className="flex flex-col gap-2.5 ps-6 pb-2">
                <CallArguments part={call.part} files={files} />
                <CallResult part={call.part} sessionId={sessionId} />
              </div>
            </Collapsible>
          );
        })}
      </CollapsibleGroup>
    </div>
  );

  return (
    <div className="border-ax-border bg-ax-card rounded-ax-element flex flex-col overflow-hidden border">
      {calls.length > 1 ? (
        // Several calls: a grey group header that folds the rows away.
        <Collapsible
          defaultIsOpen
          className="[&>.astryx-collapsible-trigger]:bg-ax-muted [&>.astryx-collapsible-trigger]:text-ax-text-secondary [&>.astryx-collapsible-trigger[aria-expanded=true]]:border-ax-border [&>.astryx-collapsible-trigger]:min-h-8 [&>.astryx-collapsible-trigger]:px-2.5 [&>.astryx-collapsible-trigger]:text-[12px] [&>.astryx-collapsible-trigger]:font-medium [&>.astryx-collapsible-trigger[aria-expanded=true]]:border-b"
          trigger={
            <span className="flex items-center gap-2">
              <Wrench aria-hidden="true" className="size-3.5 shrink-0" />
              <span className="truncate">
                {[t("chat_activity_tool_calls", { count: calls.length }), serverLine]
                  .filter(Boolean)
                  .join(" · ")}
              </span>
            </span>
          }
        >
          {rows}
        </Collapsible>
      ) : (
        <>
          {serverLine && (
            <p className="text-ax-text-secondary border-ax-border bg-ax-muted border-b px-2.5 py-1.5 text-[12px] font-medium">
              {serverLine}
            </p>
          )}
          {rows}
        </>
      )}
    </div>
  );
}
