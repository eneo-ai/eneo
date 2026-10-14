import type { IntegrationKnowledge } from "@eneo/eneo-js";
import type { IntegrationSkippedDocuments } from "./integrationDocuments";
import { describeSkipReason, skipReasonKind, type SkipReasonKind } from "./skipReasons";

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

const CATEGORY_BY_KIND: Record<SkipReasonKind, FileProblemCategory> = {
  no_text_layer: "no_text_layer",
  file_too_large: "too_large",
  extraction_limit: "too_much_text",
  password_protected: "password_protected",
  corrupt_file: "corrupt",
  empty_content: "empty",
  incomplete_download: "transient",
  error: "transient",
  unsupported_type: "unsupported"
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

export type SyncFailure = { item: IntegrationKnowledge; message: string };

export type SourceProblems = {
  /** Set when the sign-in failed; every item listed stopped updating. */
  credentials: { items: IntegrationKnowledge[]; lastSyncedAt: string | null } | null;
  failures: SyncFailure[];
  fixable: FileProblemGroup[];
  intentional: FileProblemGroup[];
  /** Skipped files the capped per-item lists leave out. */
  notListed: number;
  /** Items whose skipped list could not be loaded. */
  unavailable: IntegrationKnowledge[];
  /** What needs someone's attention: blocking failures plus fixable files. */
  attentionCount: number;
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
  const failures: SyncFailure[] = [];
  const groups = new Map<FileProblemCategory, FileProblemGroup>();
  const unavailable: IntegrationKnowledge[] = [];
  let notListed = 0;

  for (const item of items) {
    const metadata = item.metadata;
    if (metadata?.last_sync_status === "error") {
      const message = metadata.last_sync_error?.trim() ?? "";
      if (isCredentialsError(message)) {
        credentialItems.push(item);
        credentialsLastSynced = latest(credentialsLastSynced, metadata.last_synced_at);
      } else {
        failures.push({ item, message });
      }
    }

    const skipped = skippedByItem[item.id];
    if (skipped === null) {
      unavailable.push(item);
      continue;
    }
    if (!skipped) continue;
    if (skipped.truncated) notListed += Math.max(0, skipped.total - skipped.items.length);
    for (const entry of skipped.items) {
      const category = CATEGORY_BY_KIND[skipReasonKind(entry.reason)];
      let group = groups.get(category);
      if (!group) {
        group = { category, severity: fileProblemSeverity(category), files: [] };
        groups.set(category, group);
      }
      group.files.push({ file: entry.file, detail: describeSkipReason(entry.reason), item });
    }
  }

  const ordered = CATEGORY_ORDER.flatMap((category) => {
    const group = groups.get(category);
    return group ? [group] : [];
  });
  const fixable = ordered.filter((group) => group.severity === "fixable");
  const intentional = ordered.filter((group) => group.severity === "intentional");

  return {
    credentials:
      credentialItems.length > 0
        ? { items: credentialItems, lastSyncedAt: credentialsLastSynced }
        : null,
    failures,
    fixable,
    intentional,
    notListed,
    unavailable,
    attentionCount:
      (credentialItems.length > 0 ? 1 : 0) +
      failures.length +
      fixable.reduce((sum, group) => sum + group.files.length, 0)
  };
}
