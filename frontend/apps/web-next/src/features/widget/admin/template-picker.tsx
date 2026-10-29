"use client";

import { Badge } from "@astryxdesign/core/Badge";
import { RadioList, RadioListItem } from "@astryxdesign/core/RadioList";
import { useTranslations } from "next-intl";
import { DEFAULT_PRIMARY_COLOR, isHexColor } from "../contrast";
import { templateRelease, type WidgetTemplate } from "./template-locks";

/**
 * Choose a template: a radio list where each entry shows the template's
 * colours as swatches, its name and description and whether it is the
 * organisation's default. Swatches and language come from the published
 * release, which is what a widget receives; the draft may be ahead of it.
 * Optionally offers "no template".
 */
export function TemplatePicker({
  templates,
  value,
  onChange,
  includeNone = false,
  legend
}: {
  templates: WidgetTemplate[];
  value: string;
  onChange: (value: string) => void;
  includeNone?: boolean;
  legend: string;
}) {
  const t = useTranslations();

  const accent = (template: WidgetTemplate) => {
    const colour = templateRelease(template).theme.primary_color ?? "";
    return isHexColor(colour) ? colour : DEFAULT_PRIMARY_COLOR;
  };
  const header = (template: WidgetTemplate) => {
    const colour = templateRelease(template).theme.header_color ?? "";
    return isHexColor(colour) ? colour : null;
  };
  const languageLabel = (language: WidgetTemplate["language"]) =>
    language === "sv"
      ? t("widget_admin_language_sv")
      : language === "en"
        ? t("widget_admin_language_en")
        : t("widget_admin_language_auto");

  return (
    <RadioList label={legend} isLabelHidden value={value} onChange={onChange}>
      {includeNone && (
        <RadioListItem
          value=""
          label={t("widget_admin_template_none")}
          description={t("widget_admin_template_none_description")}
        />
      )}
      {templates.map((template) => {
        const release = templateRelease(template);
        return (
          <RadioListItem
            key={template.id}
            value={template.id}
            label={
              <span className="flex flex-wrap items-center gap-2">
                {template.name}
                {template.is_default && (
                  <Badge variant="neutral" label={t("widget_admin_template_default")} />
                )}
              </span>
            }
            description={
              <span className="flex flex-col gap-1">
                {template.description && <span>{template.description}</span>}
                <span className="flex items-center gap-2" aria-hidden="true">
                  {/* The template's own colours: a swatch, like a palette. */}
                  <span
                    className="border-ax-border inline-block size-6 rounded-full border"
                    style={{ background: accent(template) }}
                  />
                  {header(template) && (
                    <span
                      className="border-ax-border inline-block h-6 w-10 rounded-md border"
                      style={{ background: header(template) ?? undefined }}
                    />
                  )}
                  <span className="text-ax-text-secondary text-xs">
                    {languageLabel(release.language)}
                  </span>
                </span>
                <span className="sr-only">
                  {t("widget_admin_template_swatch_alt", {
                    accent: accent(template),
                    header: header(template) ?? t("widget_admin_header_color_none")
                  })}
                </span>
              </span>
            }
          />
        );
      })}
    </RadioList>
  );
}
