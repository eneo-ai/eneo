import { Check, ChevronRight, X } from "lucide-react";
import { useTranslations } from "next-intl";
import { useState } from "react";
import { creditedServers, groupToolSteps, type WidgetToolStep } from "../widget-tool-steps";
import { cn } from "@/lib/utils";
import { TypingIndicator } from "./typing-indicator";

/**
 * What the assistant did before answering, for a visitor: one live line
 * while it works, then one summary line that opens to a compact timeline.
 * No raw tool names, no argument JSON, no result viewer.
 */
export function WidgetToolActivity({
  steps,
  working
}: {
  steps: WidgetToolStep[];
  working: boolean;
}) {
  const t = useTranslations();
  const latest = steps[steps.length - 1];
  const groups = groupToolSteps(steps);
  const servers = creditedServers(steps);
  const failed = steps.some((step) => step.status === "failed" || step.status === "denied");
  // Several steps sum up by what was done; each query is in the list the
  // line opens, so three searches never make one long line.
  const labels = [...new Set(steps.map((step) => step.summary))].join(" · ");
  const summary =
    steps.length > 1
      ? `${labels} · ${t("internal_tool_steps_count", { count: steps.length })}`
      : labels;
  const expandable = steps.length > 1 || steps.some((step) => step.detail);
  const [open, setOpen] = useState(false);

  const outcome = failed ? (
    <>
      <X className="text-ax-red mt-0.5 size-3.5 shrink-0" aria-hidden="true" />
      <span className="sr-only">{t("widget_activity_failed")}: </span>
    </>
  ) : (
    <>
      <Check className="text-ax-green mt-0.5 size-3.5 shrink-0" aria-hidden="true" />
      <span className="sr-only">{t("widget_activity_done")}: </span>
    </>
  );

  return (
    // Icons sit on the first line; wrapped text continues under the text, not the icon.
    <div className="text-ax-text-secondary flex flex-col gap-1 text-[13px] leading-snug">
      {working && latest ? (
        <div className="flex items-start gap-2">
          <div className="shrink-0 pt-[5px]">
            <TypingIndicator />
          </div>
          <span className="min-w-0 break-words">
            {latest.label}
            {latest.detail ? `: ${latest.detail}` : ""}…
          </span>
        </div>
      ) : expandable ? (
        <>
          <button
            type="button"
            className="hover:text-ax-text flex w-fit max-w-full items-start gap-1.5 rounded-md text-left"
            aria-expanded={open}
            onClick={() => setOpen((value) => !value)}
          >
            <ChevronRight
              className={cn("mt-0.5 size-3.5 shrink-0 transition-transform", open && "rotate-90")}
              aria-hidden="true"
            />
            {outcome}
            <span className="min-w-0 break-words">{summary}</span>
          </button>
          {open && (
            <ol className="border-ax-border ml-[7px] flex flex-col gap-1.5 border-l pt-1 pl-3.5">
              {groups.map((group, groupIndex) => (
                <li key={groupIndex} className="flex flex-wrap items-baseline gap-x-2 gap-y-1">
                  <span className="text-ax-text">{group.label}</span>
                  {group.steps.map((step, stepIndex) =>
                    step.detail ? (
                      <span
                        key={step.toolCallId ?? stepIndex}
                        className={cn(
                          "border-ax-border rounded-md border px-1.5 text-[11px] leading-5",
                          (step.status === "failed" || step.status === "denied") &&
                            "text-ax-red line-through"
                        )}
                      >
                        {step.detail}
                      </span>
                    ) : null
                  )}
                </li>
              ))}
              {servers.length > 0 && (
                <li className="text-ax-text-tertiary text-xs">
                  {t("widget_activity_via", { server: servers.join(", ") })}
                </li>
              )}
            </ol>
          )}
        </>
      ) : latest ? (
        <p className="flex items-start gap-1.5">
          {outcome}
          <span className="min-w-0 break-words">
            {latest.label}
            {latest.via && (
              <span className="text-ax-text-tertiary">
                {` · ${t("widget_activity_via", { server: latest.via })}`}
              </span>
            )}
          </span>
        </p>
      ) : null}
    </div>
  );
}
