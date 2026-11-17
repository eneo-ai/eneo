import { Token } from "@astryxdesign/core/Token";
import { useTranslations } from "use-intl";
import type { ReactNode } from "react";

/** "Indikativt": the figure comes from patterns in the answers' text, not a measurement. */
export function IndicativeTag() {
  const t = useTranslations();
  return (
    <Token
      label={t("insights_indicative")}
      size="sm"
      description={t("insights_indicative_description")}
    />
  );
}

/**
 * One figure in a `<dl>`: its name, its value (or why there is none) with its
 * change when compared, and a line or two on what it is made of.
 */
export function Tile({
  label,
  isIndicative = false,
  value,
  change = null,
  details
}: {
  label: string;
  isIndicative?: boolean;
  /** The figure as text, or `empty`: why there is none ("Inga betyg"). */
  value: { text: string } | { empty: string };
  change?: ReactNode;
  details: (string | null)[];
}) {
  return (
    <div className="border-ax-border rounded-ax-container flex min-w-0 flex-col gap-1 border p-4">
      <dt className="text-ax-text-secondary flex flex-wrap items-center gap-2 text-sm">
        {label}
        {isIndicative ? <IndicativeTag /> : null}
      </dt>
      <dd className="flex flex-wrap items-baseline gap-x-2 gap-y-1">
        {"text" in value ? (
          <span className="text-3xl font-semibold tabular-nums">{value.text}</span>
        ) : (
          <span className="text-ax-text-secondary py-1.5 text-lg font-medium">{value.empty}</span>
        )}
        {change}
      </dd>
      {details
        .filter((detail): detail is string => Boolean(detail))
        .map((detail) => (
          <dd key={detail} className="text-ax-text-secondary text-sm">
            {detail}
          </dd>
        ))}
    </div>
  );
}
