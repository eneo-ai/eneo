"use client";

import { Check, Equal, Loader2, TriangleAlert } from "lucide-react";
import { useTranslations } from "next-intl";
import { describeSkipReason } from "../skip-reasons";
import type { IntegrationSyncProgress, SyncProgressFile } from "../sync-progress";

/** Enough to see the sync move without pushing the documents below the fold. */
const SHOWN = 5;

const OUTCOME_LABEL: Record<SyncProgressFile["outcome"], string> = {
  indexed: "integration_live_indexed",
  unchanged: "integration_live_unchanged",
  skipped: "integration_live_skipped"
};

function OutcomeIcon({ outcome }: { outcome: SyncProgressFile["outcome"] }) {
  if (outcome === "indexed") {
    return <Check className="text-ax-success size-4 shrink-0" aria-hidden="true" />;
  }
  if (outcome === "unchanged") {
    return <Equal className="text-ax-text-secondary size-4 shrink-0" aria-hidden="true" />;
  }
  return <TriangleAlert className="text-ax-warning size-4 shrink-0" aria-hidden="true" />;
}

/**
 * The file a folder's sync reads right now and the last few it finished.
 * Not a live region: it changes every poll, which would drown a screen reader.
 */
export function LiveSyncFeed({ progress }: { progress: IntegrationSyncProgress }) {
  const t = useTranslations();
  const recent = (progress.recent ?? []).slice(0, SHOWN);
  if (!progress.current && recent.length === 0) return null;
  const headingId = `live-sync-${progress.integration_knowledge_id}`;
  return (
    <section
      aria-labelledby={headingId}
      className="border-ax-border rounded-ax-container flex flex-col border"
    >
      <h3
        id={headingId}
        className="text-ax-text-secondary border-ax-border border-b px-4 py-2 text-xs font-semibold tracking-wide uppercase"
      >
        {t("integration_live_heading")}
      </h3>
      <ul className="flex flex-col text-sm">
        {progress.current ? (
          <li className="flex items-center gap-3 px-4 py-2">
            <Loader2
              className="text-ax-text-accent size-4 shrink-0 motion-safe:animate-spin"
              aria-hidden="true"
            />
            <span className="min-w-0 flex-1 truncate font-medium">{progress.current}</span>
            <span className="text-ax-text-accent shrink-0 text-xs">
              {t("integration_live_reading")}
            </span>
          </li>
        ) : null}
        {recent.map((file, index) => {
          const reason =
            file.outcome === "skipped" && (file.code || file.reason)
              ? describeSkipReason(file, t)
              : null;
          return (
            <li
              // The same file name can recur across folders, so the key needs the position.
              key={`${index}:${file.name}`}
              className="border-ax-border flex items-center gap-3 border-t px-4 py-2"
            >
              <OutcomeIcon outcome={file.outcome} />
              <span className="flex min-w-0 flex-1 flex-col">
                <span className="truncate">{file.name}</span>
                {reason ? (
                  <span className="text-ax-text-secondary text-xs break-words">{reason}</span>
                ) : null}
              </span>
              <span
                className={`shrink-0 text-xs ${file.outcome === "skipped" ? "text-ax-warning" : "text-ax-text-secondary"}`}
              >
                {t(OUTCOME_LABEL[file.outcome])}
              </span>
            </li>
          );
        })}
      </ul>
    </section>
  );
}
