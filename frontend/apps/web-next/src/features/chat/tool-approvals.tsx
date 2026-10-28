"use client";

import { BottomSheet } from "@astryxdesign/core/BottomSheet";
import { Button } from "@astryxdesign/core/Button";
import { Collapsible } from "@astryxdesign/core/Collapsible";
import { IconButton } from "@astryxdesign/core/IconButton";
import { MetadataList, MetadataListItem } from "@astryxdesign/core/MetadataList";
import { useMutation } from "@tanstack/react-query";
import { ChevronRight, ShieldAlert, X } from "lucide-react";
import { useTranslations } from "next-intl";
import { createContext, useContext, useEffect, useId, useMemo, useRef, useState } from "react";
import { browserApi } from "@/lib/api/browser";
import { unwrap } from "@/lib/api/errors";
import { toastApiError } from "@/lib/api/toast";
import type { ToolApprovalData, ToolCallInfo } from "@/lib/chat/types";
import { humanizeToolName, readableArguments } from "./tool-presentation";

export type ToolDecision = "approved" | "denied";
type DecisionItem = { tool_call_id: string; approved: boolean };

/** A decision's key: a provider may reuse a call id in a later turn, an approval id is new each time. */
const decisionKey = (approvalId: string, toolCallId: string) => `${approvalId}:${toolCallId}`;

export type ToolApprovals = {
  /** Decisions sent from here, by approval and call: they win while the stream catches up. */
  decisions: Record<string, ToolDecision>;
  /** The control whose decision is being sent; it stays busy and enabled. */
  running: string | null;
  /** Sends decisions for one approval; ignored while another is being sent. */
  decide: (approvalId: string, control: string, items: DecisionItem[]) => void;
  /** The approval the phone's decision bar is asking about: its card only records. */
  barApprovalId?: string | null;
};

/**
 * The decisions on tool calls: one owner for a chat view, so the card in the
 * transcript and the phone's decision bar (decision 26) read and make the same
 * ones. The backend takes a partial set and tracks the rest; the open stream
 * continues as decisions arrive.
 */
export function useToolApprovalState(): ToolApprovals {
  const t = useTranslations();
  const [decisions, setDecisions] = useState<Record<string, ToolDecision>>({});
  const [running, setRunning] = useState<string | null>(null);
  const submit = useMutation({
    mutationFn: ({ approvalId, items }: { approvalId: string; items: DecisionItem[] }) =>
      unwrap(
        browserApi.POST("/api/v1/conversations/approve-tools/", {
          params: { query: { approval_id: approvalId } },
          body: items
        })
      ),
    onSuccess: (_, { approvalId, items }) =>
      setDecisions((previous) => {
        const next = { ...previous };
        for (const item of items) {
          next[decisionKey(approvalId, item.tool_call_id)] = item.approved ? "approved" : "denied";
        }
        return next;
      }),
    onError: (error) => toastApiError(error, t),
    onSettled: () => setRunning(null)
  });
  const busy = running !== null || submit.isPending;
  const { mutate } = submit;
  return useMemo(
    () => ({
      decisions,
      running,
      decide: (approvalId, control, items) => {
        if (busy) return;
        setRunning(control);
        mutate({ approvalId, items });
      }
    }),
    [decisions, running, busy, mutate]
  );
}

/** The chat view's decisions; see `useToolApprovalState`. */
export const ToolApprovalsContext = createContext<ToolApprovals | null>(null);

/** The decisions of the chat view around, or the card's own outside one (a saved conversation elsewhere). */
export function useToolApprovals(): ToolApprovals {
  const own = useToolApprovalState();
  return useContext(ToolApprovalsContext) ?? own;
}

/**
 * How a tool's call stands: decided here (wins while its request is in
 * flight), decided in the stream (another tab), or still open.
 */
export function toolDecision(
  tool: ToolCallInfo,
  data: ToolApprovalData,
  decisions: Record<string, ToolDecision>
): ToolDecision | undefined {
  const local = tool.tool_call_id
    ? decisions[decisionKey(data.approval_id, tool.tool_call_id)]
    : undefined;
  if (local) return local;
  if (data.status === "pending" || data.status === "timeout_denied") return undefined;
  return tool.approved ? "approved" : "denied";
}

/** The calls of an approval still waiting for a decision. */
export function pendingTools(
  data: ToolApprovalData,
  decisions: Record<string, ToolDecision>
): ToolCallInfo[] {
  if (data.status === "timeout_denied") return [];
  return data.tools.filter((tool) => tool.tool_call_id && !toolDecision(tool, data, decisions));
}

/** What a tool is called for people: its title, else its server and id. */
export function toolLabel(tool: ToolCallInfo): string {
  return tool.title?.trim() || `${tool.server_name}/${tool.tool_name}`;
}

/**
 * What a call will be given (decision 12): the arguments in one line, and
 * every argument in full behind "Visa alla argument", key over value so
 * nothing approved is cut off.
 */
export function ToolArguments({ tool }: { tool: ToolCallInfo }) {
  const t = useTranslations();
  const args = tool.arguments ?? {};
  const entries = Object.entries(args);
  if (entries.length === 0) return null;
  const summary = readableArguments(args);
  return (
    <div className="flex min-w-0 flex-col gap-1">
      {summary && (
        // Three lines at most: every argument, in full, is behind "Visa alla argument".
        <p className="text-ax-text-secondary line-clamp-3 text-[13px] wrap-anywhere">{summary}</p>
      )}
      <Collapsible
        defaultIsOpen={false}
        trigger={
          <span className="flex min-h-6 items-center text-[13px] font-medium pointer-coarse:min-h-11">
            {t("chat_tool_all_arguments")}
          </span>
        }
      >
        <MetadataList label={{ position: "top" }}>
          {entries.map(([key, value]) => (
            <MetadataListItem key={key} label={humanizeToolName(key)}>
              <span className="font-mono text-[13px] wrap-anywhere whitespace-pre-wrap">
                {typeof value === "string" ? value : JSON.stringify(value, null, 2)}
              </span>
            </MetadataListItem>
          ))}
        </MetadataList>
      </Collapsible>
    </div>
  );
}

/** Avvisa and Godkänn: an equal pair, primary last, each naming what it decides. */
function DecisionPair({
  data,
  tools,
  control
}: {
  data: ToolApprovalData;
  tools: ToolCallInfo[];
  /** Tells this pair's busy button from the card's. */
  control: string;
}) {
  const t = useTranslations();
  const { running, decide } = useToolApprovals();
  const many = tools.length > 1;
  const one = tools[0];
  const send = (approved: boolean) =>
    decide(
      data.approval_id,
      `${control}:${approved ? "accept" : "deny"}`,
      tools.map((tool) => ({ tool_call_id: tool.tool_call_id ?? "", approved }))
    );
  if (!one) return null;
  return (
    <div className="grid grid-cols-2 gap-2">
      <Button
        variant="secondary"
        label={many ? t("tool_deny_all") : t("chat_tool_deny_named", { tool: toolLabel(one) })}
        width="100%"
        isLoading={running === `${control}:deny`}
        isInterruptible
        onClick={() => send(false)}
      >
        {many ? t("tool_deny_all") : t("tool_deny")}
      </Button>
      <Button
        variant="primary"
        label={
          many
            ? t("tool_accept_all", { count: tools.length })
            : t("chat_tool_accept_named", { tool: toolLabel(one) })
        }
        width="100%"
        isLoading={running === `${control}:accept`}
        isInterruptible
        onClick={() => send(true)}
      >
        {many ? t("tool_accept_all", { count: tools.length }) : t("tool_accept")}
      </Button>
    </div>
  );
}

/**
 * Decision 26: on a phone, while calls wait, the composer's place holds the
 * decision, in thumb reach however far the conversation scrolls: who wants to
 * use what, the arguments in up to two lines, "Granska" for all of them, and
 * the pair. It takes the focus when it takes the composer's place; the
 * waiting is announced by the view (useAnnounce). Toasts rise above it while
 * it has the focus (toast-lift.ts).
 */
export function ToolDecisionBar({
  data,
  assistantName
}: {
  data: ToolApprovalData;
  assistantName: string;
}) {
  const t = useTranslations();
  const headingId = useId();
  const sheetHeadingId = useId();
  const { decisions } = useToolApprovals();
  const pending = pendingTools(data, decisions);
  const [reviewing, setReviewing] = useState(false);
  const ref = useRef<HTMLElement>(null);
  // Safari does not focus a tapped button: closing the sheet comes back here.
  const reviewButton = useRef<HTMLButtonElement>(null);
  useEffect(() => {
    // The composer it replaces had the focus, or nothing has: take it.
    if (document.activeElement === document.body) ref.current?.focus();
  }, []);

  const one = pending[0];
  if (!one) return null;
  const many = pending.length > 1;
  const summary = !many && one.arguments ? readableArguments(one.arguments) : null;
  const subject = many ? t("chat_tool_count", { count: pending.length }) : toolLabel(one);
  return (
    <>
      <section
        ref={ref}
        tabIndex={-1}
        aria-labelledby={headingId}
        data-clear-of-toasts=""
        className="bg-ax-surface border-ax-border-strong rounded-ax-page focus-visible:outline-ring flex flex-col gap-3 border p-3 focus-visible:outline-2 focus-visible:outline-offset-2"
      >
        <div className="flex items-start gap-2.5 px-1">
          <ShieldAlert aria-hidden="true" className="text-ax-warning mt-0.5 size-4 shrink-0" />
          <div className="flex min-w-0 flex-1 flex-col gap-0.5">
            <h2 id={headingId} className="text-[15px] leading-5 font-semibold text-pretty">
              {many
                ? t("chat_tool_wants_many", { assistant: assistantName, count: pending.length })
                : t("chat_tool_wants", { assistant: assistantName, tool: toolLabel(one) })}
            </h2>
            {summary && (
              // Two lines at most, so the pair stays in reach; Granska has it all.
              <p className="text-ax-text-secondary line-clamp-2 text-[13px] wrap-anywhere">
                {summary}
              </p>
            )}
            <div className="-ms-3">
              <Button
                ref={reviewButton}
                variant="ghost"
                label={t("chat_tool_review_named", { tool: subject })}
                aria-haspopup="dialog"
                endContent={<ChevronRight aria-hidden="true" className="size-4" />}
                onClick={() => setReviewing(true)}
              >
                {t("chat_tool_review")}
              </Button>
            </div>
          </div>
        </div>
        <DecisionPair data={data} tools={pending} control="bar" />
      </section>
      {/* A modal of its own, beside the bar rather than inside its region. */}
      <BottomSheet
        isOpen={reviewing}
        onOpenChange={setReviewing}
        label={subject}
        height="hug"
        finalFocusRef={reviewButton}
      >
        {/* pt clears the sheet's grab handle. */}
        <div className="flex flex-col gap-4 px-4 pt-7">
          <div className="flex items-start justify-between gap-2">
            <h2 id={sheetHeadingId} className="pt-2 text-[17px] leading-snug font-semibold">
              {subject}
            </h2>
            <IconButton
              label={t("close")}
              icon={<X className="size-5" />}
              variant="ghost"
              onClick={() => setReviewing(false)}
            />
          </div>
          {pending.map((tool) => (
            <section key={tool.tool_call_id} className="flex flex-col gap-2">
              {many && <h3 className="text-[15px] font-semibold">{toolLabel(tool)}</h3>}
              <span className="text-ax-text-secondary font-mono text-[13px] wrap-anywhere">
                {tool.server_name}/{tool.tool_name}
              </span>
              <ToolArguments tool={tool} />
            </section>
          ))}
          {/* Decide without closing it first; the pair stays at the sheet's foot. */}
          <div className="bg-ax-surface sticky bottom-0 -mx-4 px-4 pt-2 pb-4">
            <DecisionPair data={data} tools={pending} control="sheet" />
          </div>
        </div>
      </BottomSheet>
    </>
  );
}
