"use client";

import { ToggleButton, ToggleButtonGroup } from "@astryxdesign/core/ToggleButton";
import { SendHorizontal } from "lucide-react";
import { useTranslations } from "next-intl";
import { useId, useState } from "react";
import type { Schema } from "@/lib/api/models";
import { WidgetPersonaByline } from "../../components/widget-persona-byline";
import { contrastRatio, readableOn, themeColors } from "../../contrast";
import { avatarIconUrl, monogram } from "../../persona";
import { linkHost } from "../../urls";
import { useAppScheme } from "../use-app-scheme";

type WidgetTexts = Schema<"WidgetTexts">;
type WidgetTheme = Schema<"WidgetTheme">;
type WidgetPersona = Schema<"WidgetPersona">;

/** The loader's launcher glyph, so the mock reads like the real button. */
function ChatGlyph({ className }: { className: string }) {
  return (
    <svg viewBox="0 0 24 24" className={className} fill="currentColor" aria-hidden="true">
      <path d="M4 3h16a2 2 0 0 1 2 2v10a2 2 0 0 1-2 2H9l-5 4v-4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2z" />
    </svg>
  );
}

/**
 * A static rendering of how a template's colours, logo and texts come
 * together: launcher, header, welcome, a sample bubble and the composer.
 * Templates have no widget behind them, so there is nothing live to frame;
 * the real embed page is previewed on the widget page after the template has
 * been applied.
 */
export function WidgetMockPreview({
  name,
  texts,
  theme,
  persona = null
}: {
  name: string;
  texts: WidgetTexts;
  theme: WidgetTheme;
  persona?: WidgetPersona | null;
}) {
  const t = useTranslations();
  const titleId = useId();
  const appScheme = useAppScheme();

  // Previewed in the scheme the template pins, else what the admin sees in
  // Eneo; the toggle lets them check the other one.
  const pinned =
    theme.color_scheme === "light" || theme.color_scheme === "dark" ? theme.color_scheme : null;
  const [chosen, setChosen] = useState<"light" | "dark" | null>(null);
  const scheme = pinned ?? chosen ?? appScheme;
  const dark = scheme === "dark";

  // What the embed page shows: the same byline, the same avatar rule.
  const personaName = persona?.name;
  const personaPreview = personaName
    ? {
        name: personaName,
        avatarUrl: persona?.avatar_icon_id ? avatarIconUrl(persona.avatar_icon_id) : null,
        monogram: monogram(personaName),
        inLauncher: !!persona?.avatar_icon_id && (persona?.avatar_in_launcher ?? false)
      }
    : null;

  const colors = themeColors(theme, dark);
  const accent = colors.accent;
  const header = colors.header;
  const radius = `${theme.radius ?? 12}px`;
  const left = theme.position === "bottom-left";
  const avatarOnAccent = contrastRatio(readableOn(accent), accent) >= 4.5;

  return (
    <section
      aria-labelledby={titleId}
      className="bg-ax-card border-ax-border flex flex-col gap-3 rounded-xl border p-4"
    >
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 id={titleId} className="text-base font-semibold">
          {t("widget_admin_template_preview")}
        </h2>
        <ToggleButtonGroup
          label={t("widget_admin_preview_scheme")}
          size="sm"
          value={scheme}
          onChange={(next) => {
            if (next === "light" || next === "dark") setChosen(next);
          }}
        >
          <ToggleButton
            value="light"
            label={t("widget_admin_scheme_light")}
            isDisabled={pinned !== null}
          />
          <ToggleButton
            value="dark"
            label={t("widget_admin_scheme_dark")}
            isDisabled={pinned !== null}
          />
        </ToggleButtonGroup>
      </div>
      <p className="text-ax-text-secondary text-sm">
        {t("widget_admin_template_preview_description")}
      </p>

      <div
        className={`bg-ax-muted flex items-end gap-3 rounded-lg p-4 ${left ? "flex-row-reverse" : ""}`}
        data-theme={scheme}
        role="img"
        aria-label={t("widget_admin_template_preview_alt", { name })}
        style={
          {
            colorScheme: scheme,
            "--widget-avatar-bg": avatarOnAccent ? accent : undefined,
            "--widget-avatar-fg": avatarOnAccent ? readableOn(accent) : undefined
          } as React.CSSProperties
        }
      >
        <div
          className="bg-ax-surface text-ax-text flex w-full max-w-sm flex-col overflow-hidden shadow"
          style={{ borderRadius: radius }}
        >
          <div
            className={`flex items-center gap-3 px-4 py-3 ${header ? "" : "border-ax-border border-b"}`}
            style={{
              background: header ?? undefined,
              color: header ? readableOn(header) : undefined
            }}
          >
            {theme.logo_url && (
              // The organisation's own host serves the logo; nothing fits next/image.
              // eslint-disable-next-line @next/next/no-img-element
              <img
                className="size-8 shrink-0 rounded-md object-contain"
                src={theme.logo_url}
                alt=""
                width="32"
                height="32"
              />
            )}
            <div className="min-w-0">
              <p className="truncate text-base font-semibold">{texts.title || name}</p>
              <p className={`text-xs ${header ? "opacity-85" : "text-ax-text-secondary"}`}>
                {texts.subtitle}
              </p>
            </div>
          </div>
          <div className="flex flex-col gap-3 px-4 py-4">
            {personaPreview && <WidgetPersonaByline persona={personaPreview} />}
            {texts.welcome && <p className="text-sm whitespace-pre-wrap">{texts.welcome}</p>}
            <div className="flex justify-end">
              <span
                className="max-w-[80%] px-3 py-2 text-sm"
                style={{
                  background: accent,
                  color: readableOn(accent),
                  borderRadius: radius,
                  borderBottomRightRadius: "4px"
                }}
              >
                {t("widget_admin_template_preview_sample_question")}
              </span>
            </div>
          </div>
          <div className="border-ax-border flex flex-col gap-2 border-t px-4 py-3">
            <div
              className="border-ax-border text-ax-text-secondary flex items-center justify-between border px-3 py-2 text-sm"
              style={{ borderRadius: radius }}
            >
              <span>{texts.placeholder || t("widget_input_placeholder")}</span>
              <span
                className="inline-flex size-7 shrink-0 items-center justify-center rounded-full"
                style={{ background: accent, color: readableOn(accent) }}
                aria-hidden="true"
              >
                <SendHorizontal className="size-4" />
              </span>
            </div>
            {(texts.footer_text || texts.footer_link_url) && (
              <p className="text-ax-text-secondary text-xs">
                {texts.footer_text}{" "}
                {texts.footer_link_url && (
                  <span className="underline underline-offset-2">
                    {texts.footer_link_label || linkHost(texts.footer_link_url)}
                  </span>
                )}
              </p>
            )}
          </div>
        </div>
        {personaPreview?.inLauncher && personaPreview.avatarUrl ? (
          // The avatar as the launcher: ringed in the accent, with the chat
          // glyph as a badge so it still reads as a chat.
          <span className="relative inline-block size-14 shrink-0" aria-hidden="true">
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img
              className="size-14 rounded-full object-cover shadow"
              style={{ border: `2px solid ${accent}` }}
              src={personaPreview.avatarUrl}
              alt=""
              width="56"
              height="56"
            />
            <span
              className="border-ax-surface absolute -right-0.5 -bottom-0.5 inline-flex size-6 items-center justify-center rounded-full border-2"
              style={{ background: accent, color: readableOn(accent) }}
            >
              <ChatGlyph className="size-3.5" />
            </span>
          </span>
        ) : (
          <span
            className="inline-flex size-14 shrink-0 items-center justify-center rounded-full shadow"
            style={{ background: accent, color: readableOn(accent) }}
            aria-hidden="true"
          >
            <ChatGlyph className="size-7" />
          </span>
        )}
      </div>
    </section>
  );
}
