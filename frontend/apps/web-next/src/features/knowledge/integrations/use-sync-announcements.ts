"use client";

import { useAnnounce } from "@astryxdesign/core/hooks";
import { useTranslations } from "next-intl";
import { useEffect, useRef } from "react";
import type { SourceSummary } from "./sources";
import {
  announceProblemCount,
  announceSourceChange,
  sourceSnapshot,
  type SourceSnapshot
} from "./sync-announcements";

// Spoken through Astryx's one polite live region (ACCESSIBILITY.md, status
// messages). The effects follow a serialised snapshot, so a poll that changes
// nothing they speak of does not run them.

/**
 * A source page's sync course and problem count, spoken as they change: a
 * sync being queued, starting, its count at most every 10 s or on a phase
 * change, progress stopping (the job reports the outcome), and changes to the
 * problem count (null while the lists load).
 */
export function useSourceAnnouncements(
  name: string,
  summary: SourceSummary,
  problemCount: number | null
) {
  const t = useTranslations();
  const announce = useAnnounce();
  const previous = useRef<SourceSnapshot | null>(null);
  const progressAnnouncedAt = useRef(0);
  const previousProblems = useRef<number | null>(null);
  const key = JSON.stringify(sourceSnapshot(summary));

  useEffect(() => {
    const next = JSON.parse(key) as SourceSnapshot;
    const now = Date.now();
    const text = announceSourceChange(
      name,
      previous.current,
      next,
      now - progressAnnouncedAt.current,
      t
    );
    previous.current = next;
    const problems = announceProblemCount(previousProblems.current, problemCount, t);
    if (problemCount !== null) previousProblems.current = problemCount;
    const message = [text, problems].filter(Boolean).join(". ");
    if (message) announce(message);
    if (text && next.progress) progressAnnouncedAt.current = now;
  }, [announce, key, name, problemCount, t]);
}

/** A list's sources: each one's sync starting, stopping or being queued. */
export function useSourceListAnnouncements(
  sources: readonly { id: string; name: string; summary: SourceSummary }[]
) {
  const t = useTranslations();
  const announce = useAnnounce();
  const previous = useRef<Record<string, SourceSnapshot>>({});
  const key = JSON.stringify(
    sources.map((source) => [source.id, source.name, sourceSnapshot(source.summary)])
  );

  useEffect(() => {
    const entries = JSON.parse(key) as [string, string, SourceSnapshot][];
    const next: Record<string, SourceSnapshot> = {};
    const messages: string[] = [];
    for (const [id, name, snapshot] of entries) {
      next[id] = snapshot;
      const text = announceSourceChange(name, previous.current[id] ?? null, snapshot, 0, t, {
        speakProgress: false
      });
      if (text) messages.push(text);
    }
    previous.current = next;
    if (messages.length > 0) announce(messages.join(". "));
  }, [announce, key, t]);
}
