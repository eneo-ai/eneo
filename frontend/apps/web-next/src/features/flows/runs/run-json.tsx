import { ScrollableArea } from "@astryxdesign/core/ScrollableArea";
import { useTranslations } from "use-intl";
import { CopyButton } from "./run-copy";

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
  // An answer left blank reads as no value, not as nothing.
  if (value === null || value === undefined || (typeof value === "string" && !value.trim())) {
    return <span className="text-ax-text-secondary">{t("flow_runs_value_empty")}</span>;
  }
  if (typeof value === "boolean") return <>{value ? t("yes") : t("no")}</>;
  // `anywhere`, not `break-word`: a long id or hash then also lowers the width
  // the value asks for, so it wraps instead of widening the page.
  return <span className="[overflow-wrap:anywhere] whitespace-pre-wrap">{String(value)}</span>;
}

/**
 * A value as JSON in a block of its own, as wide as its place: lines wrap, a
 * long value scrolls within the block's height, and `copy` adds a button
 * that copies the value (or the one it names instead).
 */
export function JsonBlock({
  value,
  copy,
  maxHeight = "24rem"
}: {
  value: unknown;
  copy?: { label: string; value?: unknown };
  maxHeight?: string;
}) {
  const t = useTranslations();
  return (
    <div data-json-block className="relative min-w-0">
      {copy && (
        <div className="absolute end-2 top-2 z-10">
          <CopyButton label={copy.label} value={"value" in copy ? copy.value : value} />
        </div>
      )}
      <ScrollableArea
        axis="block"
        label={t("flow_runs_json_label")}
        className="bg-ax-sunken rounded-ax-inner focus-visible:outline-ring min-w-0 focus-visible:outline-2 focus-visible:-outline-offset-2"
        style={{ maxHeight }}
      >
        <pre className="m-0 px-3 py-2 font-mono text-xs [overflow-wrap:anywhere] break-words whitespace-pre-wrap">
          {readableJson(value, t("flow_runs_secret_stored"))}
        </pre>
      </ScrollableArea>
    </div>
  );
}

/**
 * A structured value (a form's answers, a step's JSON output) as nested
 * lists a person can read: an object's fields as name and value, a list as
 * a list. Deeper than three levels it falls back to a JSON block. A stored
 * credential shows as "Sparad, visas inte". Nothing in it widens its place:
 * the value's column starts at nothing, a name is held to 15rem, and long
 * words wrap.
 */
export function JsonValue({ value, depth = 0 }: { value: unknown; depth?: number }) {
  const t = useTranslations();
  if (isStoredSecret(value)) {
    return <span className="text-ax-text-secondary">{t("flow_runs_secret_stored")}</span>;
  }
  if (depth >= MAX_DEPTH && (isRecord(value) || Array.isArray(value))) {
    return <JsonBlock value={value} maxHeight="16rem" />;
  }
  if (Array.isArray(value)) {
    if (value.length === 0) {
      return <span className="text-ax-text-secondary">{t("flow_runs_value_empty_list")}</span>;
    }
    return (
      <ol className="flex min-w-0 list-decimal flex-col gap-1 pl-5">
        {value.map((item, index) => (
          <li key={index} className="min-w-0">
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
      <dl className="grid min-w-0 grid-cols-1 gap-x-4 gap-y-1 sm:grid-cols-[minmax(8rem,max-content)_minmax(0,1fr)]">
        {entries.map(([key, item]) => (
          <div key={key} className="contents">
            <dt className="text-ax-text-secondary max-w-60 text-sm font-medium [overflow-wrap:anywhere]">
              {key}
            </dt>
            <dd className="text-ax-text m-0 min-w-0 text-sm">
              <JsonValue value={item} depth={depth + 1} />
            </dd>
          </div>
        ))}
      </dl>
    );
  }
  return <Scalar value={value} />;
}
