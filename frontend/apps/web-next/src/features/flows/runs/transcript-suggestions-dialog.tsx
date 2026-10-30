"use client";

import { Button } from "@astryxdesign/core/Button";
import { CheckboxList, CheckboxListItem } from "@astryxdesign/core/CheckboxList";
import { Dialog, DialogHeader } from "@astryxdesign/core/Dialog";
import { Layout, LayoutContent, LayoutFooter } from "@astryxdesign/core/Layout";
import { Text } from "@astryxdesign/core/Text";
import { useTranslations } from "use-intl";
import { useState } from "react";
import { Banner } from "@astryxdesign/core/Banner";
import { clockTime, type ShownSegment } from "./transcript";
import { withCasingOf, type Candidate, type Suggestions } from "./transcript-suggestions";

const keyOf = (candidate: Candidate) => `${candidate.segmentIndex}:${candidate.charStart}`;

/**
 * Offers the other places the transcript likely says what the reviewer just
 * corrected, to correct them the same way. Exact matches start chosen, close
 * spellings do not; each shows its line with the match marked and what it
 * becomes. "Bara den här raden" (and closing) saves the one line.
 */
export function SuggestionsDialog({
  suggestions,
  lines,
  multiFile,
  saving,
  problem,
  onConfirm,
  onSkip
}: {
  suggestions: Suggestions;
  /** The shown lines, by segment index, for each place's time and text. */
  lines: ReadonlyMap<number, ShownSegment>;
  multiFile: boolean;
  saving: boolean;
  /** Why the last save did not go through. */
  problem: string | null;
  onConfirm: (chosen: Candidate[]) => void;
  onSkip: () => void;
}) {
  const t = useTranslations();
  const [chosen, setChosen] = useState<string[]>(() =>
    suggestions.candidates.filter((candidate) => candidate.kind === "exact").map(keyOf)
  );

  function where(candidate: Candidate) {
    const line = lines.get(candidate.segmentIndex);
    if (!line) return "";
    return multiFile
      ? t("flow_runs_transcript_time_in_file", {
          file: line.fileIndex + 1,
          time: clockTime(line.start)
        })
      : clockTime(line.start);
  }

  return (
    <Dialog
      isOpen
      onOpenChange={(open) => {
        if (!open && !saving) onSkip();
      }}
      purpose="form"
      width={640}
      maxHeight="85dvh"
    >
      <Layout
        height="auto"
        header={
          <DialogHeader
            title={t("flow_transcript_suggest_title")}
            onOpenChange={(open) => {
              if (!open && !saving) onSkip();
            }}
          />
        }
        content={
          <LayoutContent>
            <div className="flex flex-col gap-3">
              {problem ? (
                <Banner
                  status="error"
                  title={t("flow_transcript_line_not_saved")}
                  description={problem}
                  collapsible={false}
                />
              ) : null}
              <Text as="p">
                {t("flow_transcript_suggest_body", {
                  original: suggestions.original,
                  corrected: suggestions.corrected
                })}
              </Text>
              <CheckboxList
                label={t("flow_transcript_suggest_list")}
                value={chosen}
                onChange={setChosen}
                hasDividers
                width="100%"
              >
                {suggestions.candidates.map((candidate) => {
                  const raw = lines.get(candidate.segmentIndex)?.raw ?? candidate.matched;
                  const time = where(candidate);
                  return (
                    <CheckboxListItem
                      key={keyOf(candidate)}
                      value={keyOf(candidate)}
                      aria-label={t("flow_transcript_suggest_item", {
                        time,
                        text: raw
                      })}
                      label={
                        <span className="break-words">
                          <span className="text-ax-text-secondary tabular-nums">{time}</span>{" "}
                          {raw.slice(0, candidate.charStart)}
                          <mark className="bg-ax-accent-muted text-ax-text rounded-sm px-0.5 font-medium">
                            {candidate.matched}
                          </mark>
                          {raw.slice(candidate.charEnd)}
                        </span>
                      }
                      description={t(
                        candidate.kind === "exact"
                          ? "flow_transcript_suggest_exact"
                          : "flow_transcript_suggest_similar",
                        {
                          from: candidate.matched,
                          to: withCasingOf(candidate.matched, suggestions.corrected)
                        }
                      )}
                    />
                  );
                })}
              </CheckboxList>
            </div>
          </LayoutContent>
        }
        footer={
          <LayoutFooter>
            <div className="flex flex-wrap justify-end gap-2">
              <Button
                label={t("flow_transcript_suggest_skip")}
                onClick={() => {
                  if (!saving) onSkip();
                }}
              />
              <Button
                label={t("flow_transcript_suggest_confirm", { count: chosen.length })}
                variant="primary"
                isLoading={saving}
                isInterruptible
                onClick={() => {
                  if (saving) return;
                  onConfirm(
                    suggestions.candidates.filter((candidate) => chosen.includes(keyOf(candidate)))
                  );
                }}
              />
            </div>
          </LayoutFooter>
        }
      />
    </Dialog>
  );
}
