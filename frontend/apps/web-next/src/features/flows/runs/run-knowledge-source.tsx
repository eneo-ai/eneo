"use client";

import { Button } from "@astryxdesign/core/Button";
import { Dialog, DialogHeader } from "@astryxdesign/core/Dialog";
import { useAnnounce } from "@astryxdesign/core/hooks";
import { Layout, LayoutContent, LayoutFooter } from "@astryxdesign/core/Layout";
import { List, ListItem } from "@astryxdesign/core/List";
import { useQuery } from "@tanstack/react-query";
import { useTranslations } from "use-intl";
import { useId, useState } from "react";
import { LoadingState } from "@/components/composites/loading-state";
import { browserApi } from "@/lib/api/browser";
import { unwrap } from "@/lib/api/errors";
import type { Schema } from "@/lib/api/models";
import { highlightSegments, relevanceLevel } from "./run-chunk-highlight";

type Reference = Schema<"FlowRunDebugRagReference">;
type Passage = Schema<"RetrievedPassage">;

/** The passages of a reference the reader may see, in the source's order. */
function disclosedPassages(reference: Reference): Passage[] {
  return [...(reference.passages ?? [])]
    .filter(
      (passage) =>
        (passage.disclosure ?? "text_disclosed") === "text_disclosed" && passage.text?.trim()
    )
    .sort((a, b) => a.chunk_no - b.chunk_no);
}

function PassageMeta({ passage, best }: { passage: Passage; best: boolean }) {
  const t = useTranslations();
  return (
    <span className="text-ax-text-secondary flex flex-wrap items-center gap-x-2 text-xs">
      <span className="text-ax-text font-medium">
        {t("flow_run_knowledge_chunk_label", { chunk: passage.chunk_no })}
      </span>
      <span>{t(`flow_run_knowledge_relevance_${relevanceLevel(passage.score)}`)}</span>
      {best ? <span>{t("flow_run_knowledge_best_match")}</span> : null}
    </span>
  );
}

/** The passages as they were recorded with the run, for when the document cannot be shown. */
function RecordedPassages({ passages, note }: { passages: Passage[]; note: string }) {
  const t = useTranslations();
  return (
    <div className="flex flex-col gap-3">
      <p className="text-ax-text-secondary m-0 text-sm">{note}</p>
      <ol className="m-0 flex flex-col gap-2 p-0">
        {passages.map((passage, index) => (
          <li
            key={`${passage.chunk_no}-${index}`}
            className="border-ax-border rounded-ax-inner list-none border p-3"
          >
            <PassageMeta passage={passage} best={false} />
            <p className="text-ax-text m-0 mt-1 text-sm break-words whitespace-pre-wrap">
              {passage.text}
            </p>
            {passage.recording === "tail_truncated" ? (
              <p className="text-ax-text-secondary m-0 mt-1 text-xs">
                {t("flow_run_knowledge_passage_truncated")}
              </p>
            ) : null}
          </li>
        ))}
      </ol>
    </div>
  );
}

/**
 * One knowledge source a step retrieved from, opened in a dialog: the
 * source document with every recorded passage highlighted, a list of the
 * passages (relevance, best match) that takes the reader to each one, and
 * previous and next buttons. Going to a passage moves focus to it and
 * announces where it is; highlights carry an underline when current, so
 * colour is never the only signal. Passages the evidence policy withholds
 * and matches that were not recorded are counted, not shown. When the
 * document cannot be read, or is empty now, the passages recorded with
 * the run are shown instead.
 */
export function KnowledgeSourceViewer({
  reference,
  name,
  open,
  onOpenChange
}: {
  reference: Reference;
  name: string;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const t = useTranslations();
  const announce = useAnnounce();
  const baseId = useId();
  const [active, setActive] = useState<number | null>(null);
  const document = useQuery({
    queryKey: ["info-blobs", reference.id],
    queryFn: () =>
      unwrap(
        browserApi.GET("/api/v1/info-blobs/{id}/", { params: { path: { id: reference.id } } })
      ),
    enabled: open,
    retry: false
  });

  const passages = disclosedPassages(reference);
  const recorded = reference.passages?.length ?? 0;
  const withheld = recorded - passages.length;
  const notRecorded = Math.max(0, reference.matched_chunk_count - recorded);
  const best = passages.length > 1 ? Math.max(...passages.map((passage) => passage.score)) : null;
  const text = document.data?.text ?? "";
  const { segments, found } = highlightSegments(
    text,
    passages.map((passage) => passage.text ?? "")
  );
  const markId = (index: number) => `${baseId}-passage-${index}`;

  function goTo(index: number) {
    setActive(index);
    if (!found[index]) return;
    const mark = window.document.getElementById(markId(index));
    mark?.scrollIntoView?.({ block: "center" });
    mark?.focus({ preventScroll: true });
    announce(
      t("flow_run_journey_source_passage_now", {
        chunk: passages[index]?.chunk_no ?? index + 1,
        current: index + 1,
        total: passages.length
      })
    );
  }

  const step = (delta: number) =>
    goTo(
      active === null
        ? delta > 0
          ? 0
          : passages.length - 1
        : (active + delta + passages.length) % passages.length
    );

  const showRecorded = !document.isPending && (document.isError || !text.trim());

  return (
    <Dialog isOpen={open} onOpenChange={onOpenChange} width={1040} maxHeight="90dvh">
      <Layout
        height="auto"
        header={
          <DialogHeader
            title={name}
            subtitle={t("flow_run_journey_source_subtitle")}
            onOpenChange={onOpenChange}
          />
        }
        content={
          open ? (
            <LayoutContent>
              <div className="grid gap-4 md:grid-cols-[minmax(14rem,18rem)_minmax(0,1fr)]">
                <div className="flex min-w-0 flex-col gap-2">
                  <p className="text-ax-text m-0 text-sm font-medium">
                    {notRecorded > 0
                      ? t("flow_run_knowledge_segment_header_displayed", {
                          displayed: passages.length,
                          matched: reference.matched_chunk_count
                        })
                      : t("flow_run_knowledge_segment_header", { count: passages.length })}
                  </p>
                  {notRecorded > 0 ? (
                    <p className="text-ax-text-secondary m-0 text-xs">
                      {t("flow_run_knowledge_hidden_matched_explainer", { count: notRecorded })}
                    </p>
                  ) : null}
                  {withheld > 0 ? (
                    <p className="text-ax-text-secondary m-0 text-xs">
                      {t("flow_run_knowledge_passages_withheld", { count: withheld })}
                    </p>
                  ) : null}
                  {passages.length === 0 ? (
                    <p className="text-ax-text-secondary m-0 text-sm">
                      {withheld > 0
                        ? t("flow_run_knowledge_passages_withheld_hint")
                        : t("flow_run_knowledge_no_snippets")}
                    </p>
                  ) : (
                    <div className="max-h-[50dvh] overflow-auto">
                      <List
                        density="compact"
                        header={
                          <span className="sr-only">{t("flow_run_journey_source_passages")}</span>
                        }
                      >
                        {passages.map((passage, index) => (
                          <ListItem
                            key={`${passage.chunk_no}-${index}`}
                            label={t("flow_run_knowledge_chunk_label", { chunk: passage.chunk_no })}
                            isSelected={active === index}
                            onClick={() => goTo(index)}
                            description={
                              <span className="flex flex-col gap-0.5">
                                <span className="text-ax-text-secondary text-xs">
                                  {[
                                    t(
                                      `flow_run_knowledge_relevance_${relevanceLevel(passage.score)}`
                                    ),
                                    passage.score === best
                                      ? t("flow_run_knowledge_best_match")
                                      : null
                                  ]
                                    .filter(Boolean)
                                    .join(" · ")}
                                </span>
                                <span className="text-ax-text line-clamp-3 text-xs break-words">
                                  {passage.text}
                                </span>
                                {!showRecorded && !document.isPending && !found[index] ? (
                                  <span className="text-ax-text-secondary text-xs">
                                    {t("flow_run_journey_source_passage_not_found")}
                                  </span>
                                ) : null}
                              </span>
                            }
                          />
                        ))}
                      </List>
                    </div>
                  )}
                </div>
                <div className="min-w-0">
                  {document.isPending ? (
                    <LoadingState rows={6} label={t("flow_run_knowledge_loading_document")} />
                  ) : showRecorded ? (
                    passages.length > 0 ? (
                      <RecordedPassages
                        passages={passages}
                        note={
                          document.isError
                            ? t("flow_run_knowledge_source_unavailable_showing_recorded")
                            : t("flow_run_knowledge_source_empty_showing_recorded")
                        }
                      />
                    ) : (
                      <p className="text-ax-text-secondary m-0 text-sm">
                        {document.isError
                          ? t("flow_run_knowledge_document_load_failed")
                          : t("flow_run_knowledge_no_snippets")}
                      </p>
                    )
                  ) : (
                    <div
                      role="region"
                      aria-label={t("flow_run_journey_source_document", { name })}
                      tabIndex={0}
                      className="border-ax-border rounded-ax-inner focus-visible:outline-ring max-h-[60dvh] overflow-auto border p-4 focus-visible:outline-2 focus-visible:outline-offset-2"
                    >
                      <p className="text-ax-text m-0 text-sm leading-relaxed break-words whitespace-pre-wrap">
                        {segments.map((segment, index) =>
                          segment.passages.length === 0 ? (
                            <span key={index}>{segment.text}</span>
                          ) : (
                            <mark
                              key={index}
                              id={
                                segment.starts.length > 0 ? markId(segment.starts[0]!) : undefined
                              }
                              tabIndex={segment.starts.length > 0 ? -1 : undefined}
                              className={`text-ax-text focus-visible:outline-ring rounded-sm focus-visible:outline-2 ${
                                active !== null && segment.passages.includes(active)
                                  ? "bg-ax-warning-muted underline decoration-2 underline-offset-4"
                                  : "bg-ax-orange-muted"
                              }`}
                            >
                              {segment.text}
                            </mark>
                          )
                        )}
                      </p>
                    </div>
                  )}
                </div>
              </div>
            </LayoutContent>
          ) : null
        }
        footer={
          open ? (
            <LayoutFooter>
              <div className="flex flex-wrap items-center justify-between gap-2">
                {!showRecorded && passages.length > 0 ? (
                  <div className="flex flex-wrap items-center gap-2">
                    <Button
                      label={t("flow_run_knowledge_prev_match")}
                      size="sm"
                      onClick={() => step(-1)}
                    />
                    <span className="text-ax-text-secondary text-sm tabular-nums">
                      {active !== null
                        ? t("flow_run_knowledge_chunk_position", {
                            current: active + 1,
                            total: passages.length
                          })
                        : t("flow_run_journey_source_passage_count", { count: passages.length })}
                    </span>
                    <Button
                      label={t("flow_run_knowledge_next_match")}
                      size="sm"
                      onClick={() => step(1)}
                    />
                  </div>
                ) : (
                  <span />
                )}
                <Button label={t("done")} variant="primary" onClick={() => onOpenChange(false)} />
              </div>
            </LayoutFooter>
          ) : null
        }
      />
    </Dialog>
  );
}
