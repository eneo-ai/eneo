import type { IntegrationKnowledge } from "@eneo/eneo-js";

export type IntegrationSyncState = "never" | "success" | "error" | "empty";

export type IntegrationSyncError = {
  /** Set when the summary spans several items, so each error names its item. */
  itemName: string | null;
  message: string;
};

export type IntegrationSyncSummary = {
  state: IntegrationSyncState;
  documentCount: number;
  lastSyncedAt: string | null;
  lastSyncAttemptedAt: string | null;
  errors: IntegrationSyncError[];
};

function latest(a: string | null, b: string | null): string | null {
  if (!a) return b;
  if (!b) return a;
  return new Date(a).getTime() >= new Date(b).getTime() ? a : b;
}

export function summarizeIntegrationSync(knowledge: IntegrationKnowledge): IntegrationSyncSummary {
  const metadata = knowledge.metadata;
  const documentCount = metadata?.document_count ?? 0;
  const lastSyncedAt = metadata?.last_synced_at ?? null;
  const lastSyncAttemptedAt = metadata?.last_sync_attempted_at ?? null;
  const status = metadata?.last_sync_status ?? "never";

  if (status === "error") {
    return {
      state: "error",
      documentCount,
      lastSyncedAt,
      lastSyncAttemptedAt,
      errors: [{ itemName: null, message: metadata?.last_sync_error?.trim() ?? "" }]
    };
  }
  // Rows synced before the status column existed carry a timestamp but no status.
  if (status === "never" && lastSyncedAt === null) {
    return { state: "never", documentCount, lastSyncedAt, lastSyncAttemptedAt, errors: [] };
  }
  return {
    state: documentCount === 0 ? "empty" : "success",
    documentCount,
    lastSyncedAt,
    lastSyncAttemptedAt,
    errors: []
  };
}

/** A wrapper row: an error if any item failed, otherwise the items' documents added up. */
export function aggregateIntegrationSync(items: IntegrationKnowledge[]): IntegrationSyncSummary {
  const summaries = items.map((item) => ({
    name: item.name,
    summary: summarizeIntegrationSync(item)
  }));
  const errors = summaries
    .filter(({ summary }) => summary.state === "error")
    .map(({ name, summary }) => ({ itemName: name, message: summary.errors[0]?.message ?? "" }));
  const documentCount = summaries.reduce((sum, { summary }) => sum + summary.documentCount, 0);
  const lastSyncedAt = summaries.reduce<string | null>(
    (acc, { summary }) => latest(acc, summary.lastSyncedAt),
    null
  );
  const lastSyncAttemptedAt = summaries.reduce<string | null>(
    (acc, { summary }) => latest(acc, summary.lastSyncAttemptedAt),
    null
  );

  let state: IntegrationSyncState;
  if (errors.length > 0) state = "error";
  else if (summaries.length === 0 || summaries.every(({ summary }) => summary.state === "never"))
    state = "never";
  else state = documentCount === 0 ? "empty" : "success";

  return { state, documentCount, lastSyncedAt, lastSyncAttemptedAt, errors };
}

/** True when a source should be flagged in pickers: it failed, or it synced but holds nothing. */
export function isIntegrationSyncUnhealthy(summary: IntegrationSyncSummary): boolean {
  return summary.state === "error" || summary.state === "empty";
}
