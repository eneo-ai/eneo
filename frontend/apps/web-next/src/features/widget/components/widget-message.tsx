import { useAnnounce } from "@astryxdesign/core/hooks";
import { Check, ChevronRight, Copy, ExternalLink, FileText } from "lucide-react";
import { useTranslations } from "next-intl";
import { useCallback, useMemo, useRef, useState } from "react";
import type { PersonaView } from "../persona";
import { linkHost } from "../urls";
import {
  messageSources,
  referenceIndexer,
  sourceReferenceText,
  type WidgetSource
} from "../widget-message-context";
import { widgetToolSteps } from "../widget-tool-steps";
import { TypingIndicator } from "./typing-indicator";
import type { WidgetMessage as Message } from "./use-widget-conversation";
import { WidgetAnswer } from "./widget-answer";
import { WidgetPersonaByline } from "./widget-persona-byline";
import { WidgetQuestionBubble } from "./widget-question-bubble";
import { WidgetToolActivity } from "./widget-tool-activity";

const HTTP_URL = /^https?:\/\//i;

export function WidgetMessage({
  message,
  index,
  isLast,
  isLoading,
  showSources = true,
  showActivity = true,
  persona = null
}: {
  message: Message;
  index: number;
  isLast: boolean;
  isLoading: boolean;
  /** Off when the widget hides citations and the source list. */
  showSources?: boolean;
  /** Off when the widget keeps the tools behind an answer out of view. */
  showActivity?: boolean;
  /** Who answers; null when the widget has no persona. */
  persona?: PersonaView | null;
}) {
  const t = useTranslations();
  const announce = useAnnounce();
  const prefix = `widget-${index}`;
  const anchorFor = useCallback(
    (sourceIndex: number) => `${prefix}-source-${sourceIndex}`,
    [prefix]
  );
  const listId = `widget-sources-${index}`;
  const sources = useMemo(
    () => (showSources ? messageSources(message) : []),
    [showSources, message]
  );
  const indexer = useMemo(() => referenceIndexer(message), [message]);
  const referenceIndex = useCallback(
    (id: string) => (showSources ? indexer(id) : null),
    [showSources, indexer]
  );

  // Collapsed by default: the answer is what the visitor came for, the
  // sources are one click away, and a citation marker opens them in place.
  const [expanded, setExpanded] = useState(false);
  const [copiedId, setCopiedId] = useState<string | null>(null);
  const [copyFailedId, setCopyFailedId] = useState<string | null>(null);
  const copiedTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const revealSource = useCallback(
    (sourceIndex: number) => {
      setExpanded(true);
      requestAnimationFrame(() => {
        const entry = document.getElementById(anchorFor(sourceIndex));
        entry?.scrollIntoView({ block: "nearest" });
        entry?.focus();
      });
    },
    [anchorFor]
  );

  const sourcesLabel =
    sources.length === 1
      ? t("widget_sources_count_one", { count: sources.length })
      : t("widget_sources_count_other", { count: sources.length });

  const appOrigin = () => (typeof location === "undefined" ? "" : location.origin);

  async function copyReference(source: WidgetSource) {
    const text = sourceReferenceText(source, appOrigin());
    try {
      await navigator.clipboard.writeText(text);
      setCopiedId(source.id);
      setCopyFailedId(null);
      announce(t("widget_reference_copied"));
      if (copiedTimer.current) clearTimeout(copiedTimer.current);
      copiedTimer.current = setTimeout(() => setCopiedId(null), 2000);
    } catch {
      // Clipboard access is denied in some embedding contexts; leave the
      // text on screen so the visitor can select it instead.
      setCopyFailedId(source.id);
      announce(t("widget_reference_copy_failed"));
    }
  }

  const waiting = isLast && isLoading && message.answer.trim().length === 0;
  // Tool activity: while the assistant works only the latest step shows and
  // each new call replaces it; once done, several steps fold into one line
  // that opens to the full list. A single step never folds.
  const streaming = isLast && isLoading;
  const steps = useMemo(
    () => (showActivity ? widgetToolSteps(message, { streaming, working: waiting }, t) : []),
    [showActivity, message, streaming, waiting, t]
  );
  const stepsWorking =
    waiting || steps.some((step) => step.status === "preparing" || step.status === "running");

  return (
    <li className="widget-enter flex flex-col gap-3">
      <WidgetQuestionBubble text={message.question} />

      <div className="flex flex-col gap-2">
        {/* Before the activity row, so "Söker…" is read as the persona's step,
            and already while the answer is on its way. */}
        {persona && <WidgetPersonaByline persona={persona} />}
        {steps.length > 0 && (
          <div aria-label={t("widget_activity")} role="group">
            <WidgetToolActivity steps={steps} working={stepsWorking} />
          </div>
        )}
        {waiting && steps.length === 0 ? (
          // The chat announces the wait once; the dots stay silent.
          <div>
            <TypingIndicator />
          </div>
        ) : waiting ? null : (
          <>
            {!persona && <span className="sr-only">{t("widget_assistant")}: </span>}
            <WidgetAnswer
              answer={message.answer}
              streaming={streaming}
              sourceCount={sources.length}
              referenceIndex={referenceIndex}
              prefix={prefix}
              revealSource={revealSource}
            />
            {sources.length > 0 && (
              <section
                aria-label={t("widget_references")}
                className="border-ax-border mt-1 border-t pt-2"
              >
                <button
                  type="button"
                  className="text-ax-text-secondary hover:text-ax-text flex items-center gap-1.5 rounded-md text-sm"
                  aria-expanded={expanded}
                  aria-controls={listId}
                  onClick={() => setExpanded((value) => !value)}
                >
                  <ChevronRight
                    className={`size-4 transition-transform ${expanded ? "rotate-90" : ""}`}
                    aria-hidden="true"
                  />
                  {sourcesLabel}
                  {expanded && <span className="sr-only">({t("widget_sources_hide")})</span>}
                </button>
                {expanded && (
                  <ol id={listId} className="mt-2 flex flex-col gap-1.5 text-sm">
                    {sources.map((source, sourceIndex) => {
                      const href = source.url && HTTP_URL.test(source.url) ? source.url : null;
                      return (
                        <li
                          key={source.id}
                          id={anchorFor(sourceIndex)}
                          tabIndex={-1}
                          className="border-ax-border flex items-start gap-2.5 rounded-md border px-2.5 py-2"
                        >
                          <span
                            className="border-ax-border bg-ax-muted min-w-6 rounded-md border text-center font-mono text-xs leading-6 tabular-nums"
                            aria-hidden="true"
                          >
                            {sourceIndex + 1}
                          </span>
                          <div className="flex min-w-0 flex-1 flex-col gap-0.5">
                            {href ? (
                              <>
                                <a
                                  className="text-ax-text-accent inline-flex items-center gap-1 break-words underline-offset-2 hover:underline"
                                  href={href}
                                  target="_blank"
                                  rel="noopener noreferrer"
                                >
                                  <span className="sr-only">{sourceIndex + 1}. </span>
                                  <span className="min-w-0 break-words">{source.title}</span>
                                  <ExternalLink className="size-3.5 shrink-0" aria-hidden="true" />
                                  <span className="sr-only"> ({t("widget_open_source")})</span>
                                </a>
                                <span className="text-ax-text-secondary text-xs">
                                  {linkHost(source.url ?? "")}
                                </span>
                              </>
                            ) : (
                              <>
                                <span className="text-ax-text inline-flex items-center gap-1.5 break-words">
                                  <FileText
                                    className="text-ax-text-secondary size-3.5 shrink-0"
                                    aria-hidden="true"
                                  />
                                  <span className="sr-only">{sourceIndex + 1}. </span>
                                  <span className="min-w-0 break-words">{source.title}</span>
                                </span>
                                {!source.document ? (
                                  <span className="text-ax-text-secondary text-xs">
                                    {t("widget_source_tool")}
                                  </span>
                                ) : (
                                  <>
                                    <span className="text-ax-text-secondary text-xs">
                                      {t("widget_source_document")}
                                    </span>
                                    <button
                                      type="button"
                                      className="text-ax-text-accent mt-1 inline-flex w-fit items-center gap-1 rounded-md text-xs underline-offset-2 hover:underline"
                                      aria-label={t("widget_copy_reference_for", {
                                        title: source.title
                                      })}
                                      onClick={() => void copyReference(source)}
                                    >
                                      {copiedId === source.id ? (
                                        <>
                                          <Check className="size-3.5" aria-hidden="true" />
                                          {t("widget_reference_copied")}
                                        </>
                                      ) : (
                                        <>
                                          <Copy className="size-3.5" aria-hidden="true" />
                                          {t("widget_copy_reference")}
                                        </>
                                      )}
                                    </button>
                                    {copyFailedId === source.id && (
                                      <>
                                        <p className="text-ax-text-secondary text-xs">
                                          {t("widget_reference_copy_failed")}
                                        </p>
                                        <p className="text-ax-text text-xs break-all select-all">
                                          {sourceReferenceText(source, appOrigin())}
                                        </p>
                                      </>
                                    )}
                                    <p className="text-ax-text-secondary text-xs">
                                      {t("widget_source_request_hint")}
                                    </p>
                                  </>
                                )}
                              </>
                            )}
                          </div>
                        </li>
                      );
                    })}
                  </ol>
                )}
              </section>
            )}
          </>
        )}
      </div>
    </li>
  );
}
