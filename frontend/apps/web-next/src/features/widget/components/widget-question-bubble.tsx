import { useTranslations } from "next-intl";

/**
 * The visitor's own message, right-aligned in the widget's accent colour.
 * Shared by the settled message and the pending one shown before the first
 * chunk, so the two can never drift apart in size or shape.
 */
export function WidgetQuestionBubble({ text }: { text: string }) {
  const t = useTranslations();
  return (
    <div className="flex justify-end">
      <p className="widget-bubble max-w-[85%] px-3.5 py-2 text-sm wrap-anywhere whitespace-pre-wrap">
        <span className="sr-only">{t("widget_you")}: </span>
        {text}
      </p>
    </div>
  );
}
