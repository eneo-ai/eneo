"use client";

import { useAnnounce } from "@astryxdesign/core/hooks";
import { useTranslations } from "next-intl";
import { useEffect, useRef, useState } from "react";
import type { Translate } from "./skip-reasons";
import type { SourceSummary } from "./sources";
import {
  announceProblemCount,
  SourceAnnouncers,
  sourceSnapshot,
  type AnnouncedSource
} from "./sync-announcements";

// Spoken through Astryx's one polite live region (ACCESSIBILITY.md, status
// messages). The effects follow a serialised snapshot, so a poll that changes
// nothing they speak of does not run them. Nothing is fed before the progress
// poll has answered: the announcers take their first snapshot as what was
// already so, and a sync running at page open would otherwise sound started.

/**
 * Feeds the sources to their announcers and speaks what they say, with `also`.
 * A sync's end that waits for its outcome is fed again once the wait runs out.
 * Returns the effect's cleanup.
 */
function speak(
  announcers: SourceAnnouncers,
  sources: readonly AnnouncedSource[],
  t: Translate,
  announce: (message: string) => void,
  also: string | null = null
): () => void {
  let timer: ReturnType<typeof setTimeout> | undefined;
  const run = (extra: string | null) => {
    const { messages, recheckAt } = announcers.next(sources, Date.now(), t);
    const message = [...messages, extra].filter(Boolean).join(". ");
    if (message) announce(message);
    if (recheckAt !== null) {
      timer = setTimeout(() => run(null), Math.max(0, recheckAt - Date.now()));
    }
  };
  run(also);
  return () => clearTimeout(timer);
}

/**
 * A source page's sync course and problem count, spoken as they change: a
 * sync being queued, starting, its count at most every 10 s or on reaching the
 * last step, how it ended once the source's rows record it (else that it is no
 * longer running), and changes to the problem count (null while the lists
 * load). A change notification's background sync stays quiet. `summary` is
 * null until the progress poll has answered.
 */
export function useSourceAnnouncements(
  name: string,
  summary: SourceSummary | null,
  problemCount: number | null
) {
  const t = useTranslations();
  const announce = useAnnounce();
  const [announcers] = useState(() => new SourceAnnouncers());
  const previousProblems = useRef<number | null>(null);
  const key = summary && JSON.stringify(sourceSnapshot(summary));

  useEffect(() => {
    if (key === null) return;
    const sources = [{ id: "source", name, snapshot: JSON.parse(key) }] as AnnouncedSource[];
    const problems = announceProblemCount(previousProblems.current, problemCount, t);
    if (problemCount !== null) previousProblems.current = problemCount;
    return speak(announcers, sources, t, announce, problems);
  }, [announce, announcers, key, name, problemCount, t]);
}

/**
 * A list's sources: only a sync started from the list is spoken, its being
 * queued, starting and how it ended, without counts; the rest belongs to each
 * source's own page. `sources` is null until the progress poll has answered.
 */
export function useSourceListAnnouncements(
  sources: readonly { id: string; name: string; summary: SourceSummary }[] | null
) {
  const t = useTranslations();
  const announce = useAnnounce();
  const [announcers] = useState(
    () => new SourceAnnouncers({ speakProgress: false, onlyStartedHere: true })
  );
  const key =
    sources &&
    JSON.stringify(
      sources.map((source): AnnouncedSource => ({
        id: source.id,
        name: source.name,
        snapshot: sourceSnapshot(source.summary)
      }))
    );

  useEffect(() => {
    if (key === null) return;
    return speak(announcers, JSON.parse(key) as AnnouncedSource[], t, announce);
  }, [announce, announcers, key, t]);
}
