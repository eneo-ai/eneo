/*
 * Copyright (c) 2024 Sundsvalls Kommun
 *
 * Licensed under the MIT License.
 */

import type { CrawlRun } from "@intric/intric-js";
import type { Label } from "@intric/ui";
import type { StatusTone } from "$lib/components/StatusBadge.svelte";
import { m } from "$lib/paraglide/messages";
import {
  getCrawlOutcome,
  getCrawlOutcomeLabel,
  getCrawlOutcomeTooltip,
  getCrawlRunFailureTooltip,
  isDuplicateCrawlSkip,
  isSourceRetentionOnly
} from "$lib/features/knowledge/crawlOutcomePresentation";

export type CrawlStatusDescriptor = {
  tone: StatusTone;
  label: string;
  tooltip?: string;
};

export function labelColorToTone(color: Label.LabelColor): StatusTone {
  switch (color) {
    case "green":
      return "positive";
    case "yellow":
    case "orange":
      return "warning";
    case "red":
      return "negative";
    case "blue":
      return "info";
    case "gray":
      return "neutral";
    case "pine":
    case "amethyst":
    case "moss":
      return color;
    default:
      return "neutral";
  }
}

export type CrawlRunStatusOptions = {
  // When true (Status column), return a short generic label and let the
  // Resultat column carry the outcome-specific detail.
  // When false (overview, default), return the most specific label available.
  compact?: boolean;
};

export function getCrawlRunStatus(
  crawl: CrawlRun | undefined,
  options: CrawlRunStatusOptions = {}
): CrawlStatusDescriptor {
  const { compact = false } = options;

  if (!crawl?.status) {
    return { tone: "neutral", label: m.no_status_found() };
  }

  const outcome = getCrawlOutcome(crawl);
  const outcomeTooltip = getCrawlOutcomeTooltip(outcome, m.crawl_failed());
  const failureTooltip = getCrawlRunFailureTooltip(crawl, m.crawl_failed());
  const isDuplicateSkip = isDuplicateCrawlSkip(outcome);

  if (crawl.status === "failed" && isDuplicateSkip) {
    return {
      tone: "neutral",
      label: m.crawl_skipped(),
      tooltip: failureTooltip ?? m.crawl_skipped_duplicate()
    };
  }

  switch (crawl.status.toLowerCase()) {
    case "complete":
      if (isSourceRetentionOnly(outcome)) {
        return {
          tone: "positive",
          label: compact ? m.complete() : getCrawlOutcomeLabel(outcome, m.complete()),
          tooltip: getCrawlOutcomeTooltip(outcome, m.complete())
        };
      }
      if (hasResourceFailures(crawl)) {
        return {
          tone: "warning",
          label: m.crawl_completed_with_warnings(),
          tooltip: outcomeTooltip
        };
      }
      return { tone: "positive", label: m.complete(), tooltip: outcomeTooltip };

    case "in progress":
      return { tone: "warning", label: m.in_progress() };

    case "queued":
      return { tone: "info", label: m.queued() };

    case "failed":
    case "not found": {
      const verboseLabel = outcome
        ? getCrawlOutcomeLabel(outcome, m.crawl_failed())
        : m.crawl_failed();
      return {
        tone: "negative",
        label: compact ? m.failed() : verboseLabel,
        tooltip: failureTooltip ?? verboseLabel
      };
    }
  }

  return { tone: "neutral", label: crawl.status };
}

function hasResourceFailures(crawl: CrawlRun): boolean {
  return (crawl.pages_failed ?? 0) > 0 || (crawl.files_failed ?? 0) > 0;
}
