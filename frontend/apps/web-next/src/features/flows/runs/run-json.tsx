"use client";

import { useTranslations } from "use-intl";

/** The core's stand-in for a stored credential: `{ "$secret": "stored" }`. */
export function isStoredSecret(value: unknown): boolean {
  return (
    typeof value === "object" &&
    value !== null &&
    !Array.isArray(value) &&
    (value as Record<string, unknown>).$secret === "stored"
  );
}

/**
 * The value as JSON text for a reader, with every stored credential shown as
 * the core stores it (`{ "$secret": "stored" }` becomes a word) and never
 * as a value.
 */
export function readableJson(value: unknown, storedLabel: string): string {
  return JSON.stringify(
    value,
    (_key, item: unknown) => (isStoredSecret(item) ? `‹${storedLabel}›` : item),
    2
  );
}

const MAX_DEPTH = 3;

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function Scalar({ value }: { value: unknown }) {
  const t = useTranslations();
  if (value === null || value === undefined) {
    return <span className="text-ax-text-secondary">{t("flow_runs_value_empty")}</span>;
  }
  if (typeof value === "boolean") return <>{value ? t("yes") : t("no")}</>;
  return <span className="break-words whitespace-pre-wrap">{String(value)}</span>;
}

/**
 * A structured value (a form's answers, a step's JSON output) as nested
 * lists a person can read: an object's fields as name and value, a list as
 * a list. Deeper than three levels it falls back to indented JSON. A stored
 * credential shows as "Sparad, visas inte".
 */
export function JsonValue({ value, depth = 0 }: { value: unknown; depth?: number }) {
  const t = useTranslations();
  if (isStoredSecret(value)) {
    return <span className="text-ax-text-secondary">{t("flow_runs_secret_stored")}</span>;
  }
  if (depth >= MAX_DEPTH && (isRecord(value) || Array.isArray(value))) {
    return (
      <pre className="bg-ax-sunken rounded-ax-inner overflow-x-auto p-2 text-xs">
        {readableJson(value, t("flow_runs_secret_stored"))}
      </pre>
    );
  }
  if (Array.isArray(value)) {
    if (value.length === 0) {
      return <span className="text-ax-text-secondary">{t("flow_runs_value_empty_list")}</span>;
    }
    return (
      <ol className="flex list-decimal flex-col gap-1 pl-5">
        {value.map((item, index) => (
          <li key={index}>
            <JsonValue value={item} depth={depth + 1} />
          </li>
        ))}
      </ol>
    );
  }
  if (isRecord(value)) {
    const entries = Object.entries(value);
    if (entries.length === 0) {
      return <span className="text-ax-text-secondary">{t("flow_runs_value_empty")}</span>;
    }
    return (
      <dl className="grid grid-cols-1 gap-x-4 gap-y-1 sm:grid-cols-[minmax(8rem,max-content)_1fr]">
        {entries.map(([key, item]) => (
          <div key={key} className="contents">
            <dt className="text-ax-text-secondary text-sm font-medium break-words">{key}</dt>
            <dd className="text-ax-text m-0 text-sm">
              <JsonValue value={item} depth={depth + 1} />
            </dd>
          </div>
        ))}
      </dl>
    );
  }
  return <Scalar value={value} />;
}
