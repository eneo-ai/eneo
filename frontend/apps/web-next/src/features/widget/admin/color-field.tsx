"use client";

import { Button } from "@astryxdesign/core/Button";
import { useAnnounce } from "@astryxdesign/core/hooks";
import { useTranslations } from "next-intl";
import { useId, useState } from "react";
import { TextInput } from "@/components/astryx/text-input";
import {
  contrastRatio,
  contrastVerdict,
  DARK_SURFACE,
  DEFAULT_PRIMARY_COLOR,
  isHexColor,
  LIGHT_SURFACE,
  normalizeHexColor,
  readableOn
} from "../contrast";

/**
 * A colour: native picker plus the hex value, with an optional WCAG contrast
 * verdict against the surface it sits on and a way to clear optional colours.
 */
export function ColorField({
  label,
  description,
  value,
  onChange,
  clearable = false,
  checkContrast = false,
  checkTextOn = checkContrast,
  surface = "light",
  disabled = false,
  disabledMessage
}: {
  label: string;
  description: string;
  value: string | null;
  onChange: (value: string | null) => void;
  /** Optional colours can be cleared back to the neutral surface. */
  clearable?: boolean;
  /** Show how the colour fares against the surface it will sit on. */
  checkContrast?: boolean;
  /**
   * Warn when neither white nor near-black text reaches 4.5:1 on the colour
   * (mid-tone colours); the panel derives its text colour from it.
   */
  checkTextOn?: boolean;
  /** The surface behind the colour: the white page or the dark panel. */
  surface?: "light" | "dark";
  /** Read-only, e.g. when a template governs the appearance. */
  disabled?: boolean;
  disabledMessage?: string;
}) {
  const t = useTranslations();
  const announce = useAnnounce();
  const id = useId();
  // What is typed stays local until it is a complete hex colour; the server
  // only ever sees valid #RRGGBB values, so no error appears mid-typing.
  const [draft, setDraft] = useState(value ?? "");
  // The echo of what was just typed must not replace the draft: a six-digit
  // colour passes through a valid three-digit prefix. Adjusted during render.
  const [seen, setSeen] = useState(value ?? "");
  const saved = value ?? "";
  if (saved !== seen) {
    setSeen(saved);
    if (!isHexColor(draft) || normalizeHexColor(draft) !== saved) setDraft(saved);
  }

  const pickerValue = isHexColor(draft) ? normalizeHexColor(draft) : DEFAULT_PRIMARY_COLOR;
  const contrast =
    checkContrast && draft
      ? contrastVerdict(draft, surface === "dark" ? DARK_SURFACE : LIGHT_SURFACE)
      : null;
  const invalid = draft !== "" && !isHexColor(draft);

  function typed(raw: string) {
    const next = raw.trim();
    setDraft(next);
    if (next === "" && clearable) onChange(null);
    else if (isHexColor(next)) onChange(normalizeHexColor(next));
  }

  let contrastLabel = "";
  if (contrast) {
    const ratio = contrast.ratio.toFixed(1);
    const dark = surface === "dark";
    switch (contrast.verdict) {
      case "text":
        contrastLabel = dark
          ? t("widget_admin_contrast_dark_ok", { ratio })
          : t("widget_admin_contrast_ok", { ratio });
        break;
      case "graphics":
        contrastLabel = dark
          ? t("widget_admin_contrast_dark_graphics_only", { ratio })
          : t("widget_admin_contrast_graphics_only", { ratio });
        break;
      case "fail":
        contrastLabel = dark
          ? t("widget_admin_contrast_dark_fail", { ratio })
          : t("widget_admin_contrast_fail", { ratio });
        break;
    }
  }
  // The panel paints text in whatever reads best on the colour; for mid-tone
  // colours that is still below the 4.5:1 the visitor's messages need.
  const textOnRatio =
    checkTextOn && isHexColor(draft) ? contrastRatio(readableOn(draft), draft) : null;
  const textOnWarning =
    textOnRatio !== null && textOnRatio < 4.5
      ? t("widget_admin_contrast_text_on_fail", { ratio: textOnRatio.toFixed(1) })
      : "";

  // The verdicts are read with the field; only a change is announced.
  const verdicts = [textOnWarning, contrastLabel].filter(Boolean).join(" ");
  const [announced, setAnnounced] = useState(verdicts);
  if (verdicts !== announced) {
    setAnnounced(verdicts);
    if (verdicts) announce(verdicts);
  }

  const noteIds = [textOnWarning && `${id}-text-on`, contrastLabel && `${id}-contrast`]
    .filter(Boolean)
    .join(" ");

  return (
    <div className="flex flex-col gap-1">
      <div className="flex items-end gap-2">
        <span className="relative mb-1 h-8 w-12 shrink-0">
          {clearable && !draft && (
            // No colour chosen: an empty, dashed swatch instead of a misleading default.
            <span
              className="border-ax-border absolute inset-0 rounded-lg border border-dashed"
              aria-hidden="true"
            />
          )}
          <input
            type="color"
            className={`border-ax-border-control h-8 w-12 cursor-pointer rounded-lg border bg-transparent p-0.5 ${clearable && !draft ? "opacity-0" : ""}`}
            aria-label={`${label}: ${t("widget_admin_primary_color_picker")}`}
            value={pickerValue}
            disabled={disabled}
            onChange={(event) => typed(event.target.value)}
          />
        </span>
        <TextInput
          label={label}
          description={description}
          value={draft}
          onChange={typed}
          placeholder={clearable ? t("widget_admin_header_color_none") : DEFAULT_PRIMARY_COLOR}
          isDisabled={disabled}
          disabledMessage={disabledMessage}
          status={
            invalid ? { type: "error", message: t("widget_admin_contrast_invalid") } : undefined
          }
          aria-describedby={noteIds || undefined}
          width={180}
        />
        {clearable && draft && !disabled && (
          <Button
            variant="ghost"
            size="sm"
            label={t("widget_admin_color_reset")}
            onClick={() => {
              setDraft("");
              onChange(null);
            }}
          />
        )}
      </div>
      {textOnWarning && (
        <p id={`${id}-text-on`} className="text-ax-orange text-sm">
          {textOnWarning}
        </p>
      )}
      {contrastLabel && (
        <p
          id={`${id}-contrast`}
          className={`text-sm ${contrast?.verdict === "text" ? "text-ax-green" : "text-ax-orange"}`}
        >
          {contrastLabel}
        </p>
      )}
    </div>
  );
}
