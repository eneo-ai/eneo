import type { IntegrationKnowledge } from "@eneo/eneo-js";
import type { IntegrationSkippedDocuments } from "./integrationDocuments";
import { describeSkipReason, skipReasonKind, type SkipReasonCode } from "./skipReasons";

// Mirrors CREDENTIALS_INVALID_MESSAGE in
// backend/src/eneo/integration/infrastructure/auth_service/org_token_provider.py.
const CREDENTIALS_INVALID = "SharePoint credentials are invalid or expired";

/** The organisation's SharePoint sign-in was refused; no space member can fix it. */
export function isCredentialsError(message: string | null | undefined): boolean {
  return (message ?? "").trim().startsWith(CREDENTIALS_INVALID);
}

export type FileProblemCategory =
  | "no_text_layer"
  | "too_large"
  | "too_much_text"
  | "password_protected"
  | "corrupt"
  | "empty"
  | "transient"
  | "unsupported";

/** Fixable files can be made searchable by changing them; intentional ones never become knowledge. */
export type FileProblemSeverity = "fixable" | "intentional";

// Older versions listed unchanged files as skipped; those are no problem.
const CATEGORY_BY_CODE: Record<SkipReasonCode, FileProblemCategory | null> = {
  no_text_layer: "no_text_layer",
  file_too_large: "too_large",
  extraction_limit: "too_much_text",
  password_protected: "password_protected",
  corrupt_file: "corrupt",
  empty_content: "empty",
  incomplete_download: "transient",
  http_error: "transient",
  removal_failed: "transient",
  listing_failed: "transient",
  scope_path_unavailable: "transient",
  missing_item_id: "transient",
  error: "transient",
  unsupported_type: "unsupported",
  unchanged: null,
  set_aside: "transient"
};

const CATEGORY_ORDER: FileProblemCategory[] = [
  "no_text_layer",
  "too_large",
  "too_much_text",
  "password_protected",
  "corrupt",
  "empty",
  "transient",
  "unsupported"
];

export function fileProblemSeverity(category: FileProblemCategory): FileProblemSeverity {
  return category === "unsupported" ? "intentional" : "fixable";
}

export type ProblemFile = {
  file: string;
  /** The reason in the viewer's language, e.g. which file type or which limit. */
  detail: string;
  item: IntegrationKnowledge;
};

export type FileProblemGroup = {
  category: FileProblemCategory;
  severity: FileProblemSeverity;
  files: ProblemFile[];
};

/** Items whose latest sync failed with the same message. */
export type SyncFailure = { message: string; items: IntegrationKnowledge[] };

export type SourceProblems = {
  /** Set when the sign-in failed; every item listed stopped updating. */
  credentials: { items: IntegrationKnowledge[]; lastSyncedAt: string | null } | null;
  failures: SyncFailure[];
  fixable: FileProblemGroup[];
  intentional: FileProblemGroup[];
  /** Skipped files the capped per-item lists leave out. */
  notListed: number;
  /** When the newest of the skipped lists was written. */
  skippedAsOf: string | null;
  /** Items whose skipped list could not be loaded. */
  unavailable: IntegrationKnowledge[];
  /** Distinct things to act on: the sign-in, each failure message, each fixable cause. */
  causeCount: number;
};

function latest(a: string | null, b: string | null | undefined): string | null {
  if (!b) return a;
  if (!a) return b;
  return new Date(a).getTime() >= new Date(b).getTime() ? a : b;
}

export function buildSourceProblems(
  items: IntegrationKnowledge[],
  skippedByItem: Readonly<Record<string, IntegrationSkippedDocuments | null | undefined>>
): SourceProblems {
  const credentialItems: IntegrationKnowledge[] = [];
  let credentialsLastSynced: string | null = null;
  const failures = new Map<string, SyncFailure>();
  const groups = new Map<FileProblemCategory, FileProblemGroup>();
  const unavailable: IntegrationKnowledge[] = [];
  let notListed = 0;
  let skippedAsOf: string | null = null;

  for (const item of items) {
    const metadata = item.metadata;
    if (metadata?.last_sync_status === "error") {
      const message = metadata.last_sync_error?.trim() ?? "";
      if (isCredentialsError(message)) {
        credentialItems.push(item);
        credentialsLastSynced = latest(credentialsLastSynced, metadata.last_synced_at);
      } else {
        const failure = failures.get(message);
        if (failure) failure.items.push(item);
        else failures.set(message, { message, items: [item] });
      }
    }

    const skipped = skippedByItem[item.id];
    if (skipped === null) {
      unavailable.push(item);
      continue;
    }
    if (!skipped) continue;
    if (skipped.items.length > 0) skippedAsOf = latest(skippedAsOf, skipped.synced_at);
    if (skipped.truncated) notListed += Math.max(0, skipped.total - skipped.items.length);
    for (const entry of skipped.items) {
      const category = CATEGORY_BY_CODE[skipReasonKind(entry)];
      if (category === null) continue;
      let group = groups.get(category);
      if (!group) {
        group = { category, severity: fileProblemSeverity(category), files: [] };
        groups.set(category, group);
      }
      group.files.push({ file: entry.file, detail: describeSkipReason(entry), item });
    }
  }

  const ordered = CATEGORY_ORDER.flatMap((category) => {
    const group = groups.get(category);
    return group ? [group] : [];
  });
  const fixable = ordered.filter((group) => group.severity === "fixable");
  const intentional = ordered.filter((group) => group.severity === "intentional");
  const failureList = [...failures.values()];
  const blocking = (credentialItems.length > 0 ? 1 : 0) + failureList.length;

  return {
    credentials:
      credentialItems.length > 0
        ? { items: credentialItems, lastSyncedAt: credentialsLastSynced }
        : null,
    failures: failureList,
    fixable,
    intentional,
    notListed,
    skippedAsOf,
    unavailable,
    causeCount: blocking + fixable.length
  };
}
