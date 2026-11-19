import { Token } from "@astryxdesign/core/Token";
import { useFormatter, useTranslations } from "use-intl";
import { cn } from "@/lib/utils";
import { sourceParts, type InsightSource, type SourceCounts } from "./insight-figures";

/**
 * Each source's name, its colour as a tag, and its colour as a mark in the
 * activity chart and in a source bar. The colours are the theme's tokens,
 * which flip with the colour mode. User is the dark categorical blue and
 * widget the data amber, a lighter, warmer mark beside it (blue against
 * amber, which the common colour-vision deficiencies keep apart); API is the
 * neutral control-boundary grey. All three are 3:1 against the card and the
 * surface in both modes. A legend, a tooltip or a text always names them, so
 * colour is never the only signal.
 */
export const SOURCE_STYLE = {
  user: {
    label: "insights_source_user",
    token: "blue",
    fill: "var(--color-text-blue)",
    fillClass: "bg-ax-blue"
  },
  widget: {
    label: "insights_source_widget",
    token: "orange",
    fill: "var(--eneo-color-data-amber)",
    fillClass: "bg-ax-data-amber"
  },
  api_key: {
    label: "insights_source_api_key",
    token: "gray",
    fill: "var(--eneo-color-border-control)",
    fillClass: "bg-ax-border-control"
  }
} as const satisfies Record<
  InsightSource,
  { label: string; token: string; fill: string; fillClass: string }
>;

/**
 * Who a conversation, a question or a rating comes from: a signed-in user, a
 * website widget or a service API key. Only names the kind; widget and API
 * traffic is never tied to a person.
 */
export function SourceTag({ source }: { source: InsightSource }) {
  const t = useTranslations();
  const style = SOURCE_STYLE[source];
  return <Token label={t(style.label)} size="sm" color={style.token} />;
}

/** One source's part of a count of conversations: "3 från användare", "2 via widget". */
const SPLIT_KEY = {
  user: "insights_split_user",
  widget: "insights_split_widget",
  api_key: "insights_split_api_key"
} as const satisfies Record<InsightSource, string>;

/**
 * Conversations split by source, in words that count conversations, not
 * people: "3 från användare, 2 via widget och 1 via API". Sources without any
 * are left out; null when there are none at all.
 */
export function useSourceSplit(): (counts: SourceCounts) => string | null {
  const t = useTranslations();
  const format = useFormatter();
  return (counts) => {
    const parts = sourceParts(counts).map(({ source, count }) => t(SPLIT_KEY[source], { count }));
    return parts.length > 0 ? format.list(parts, { type: "conjunction" }) : null;
  };
}

/** Names each source's colour in a chart or a source bar, in the page's order. */
export function SourceLegend({
  sources,
  className
}: {
  sources: readonly InsightSource[];
  className?: string;
}) {
  const t = useTranslations();
  return (
    <ul className={cn("text-ax-text-secondary flex flex-wrap gap-x-4 gap-y-1 text-sm", className)}>
      {sources.map((source) => (
        <li key={source} className="inline-flex items-center gap-1.5">
          <span
            aria-hidden="true"
            className={cn("size-3 rounded-sm", SOURCE_STYLE[source].fillClass)}
          />
          {t(SOURCE_STYLE[source].label)}
        </li>
      ))}
    </ul>
  );
}
