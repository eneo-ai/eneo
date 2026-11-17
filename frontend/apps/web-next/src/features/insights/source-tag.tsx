import { Token } from "@astryxdesign/core/Token";
import { useTranslations } from "use-intl";
import { cn } from "@/lib/utils";
import type { InsightSource } from "./insight-figures";

/**
 * Each source's name, and its colour as a tag, in the activity chart and in a
 * source bar. The colours are the theme's tokens, which flip with the colour
 * mode. User and widget differ in hue (blue against amber, which the common
 * colour-vision deficiencies keep apart); API is the neutral control-boundary
 * grey, lighter than both in light mode and darker than both in dark mode,
 * and 3:1 against the card in either. A legend, a tooltip or a text always
 * names them, so colour is never the only signal.
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
    fill: "var(--color-text-orange)",
    fillClass: "bg-ax-orange"
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
