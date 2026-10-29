"use client";

import { NumberInput } from "@astryxdesign/core/NumberInput";
import { Selector } from "@astryxdesign/core/Selector";
import { useTranslations } from "next-intl";
import { useState } from "react";
import { Switch } from "@/components/astryx/switch";
import type { Schema } from "@/lib/api/models";
import { ColorField } from "./color-field";

type WidgetTheme = Schema<"WidgetTheme">;

/** Appearance: colours, shape and placement of the launcher. */
export function WidgetThemeFields({
  theme,
  onChange,
  locked = false,
  lockHint = ""
}: {
  theme: WidgetTheme;
  onChange: (change: Partial<WidgetTheme>) => void;
  /** The whole appearance is governed by a template; `lockHint` says so. */
  locked?: boolean;
  lockHint?: string;
}) {
  const t = useTranslations();
  const disabledMessage = locked ? lockHint : undefined;

  // Dark mode shows its own colour fields once switched on; switching off
  // clears them so dark mode falls back to the light-mode colours.
  const hasDarkColors = !!(theme.primary_color_dark || theme.header_color_dark);
  const [customDark, setCustomDark] = useState(hasDarkColors);
  const showDark = customDark || hasDarkColors;
  function toggleDark(checked: boolean) {
    setCustomDark(checked);
    if (!checked && hasDarkColors) onChange({ primary_color_dark: null, header_color_dark: null });
  }

  return (
    <div className="flex flex-col gap-6">
      {locked && <p className="text-ax-text-secondary text-sm">{lockHint}</p>}
      <ColorField
        label={t("widget_admin_primary_color")}
        description={t("widget_admin_primary_color_description")}
        value={theme.primary_color ?? null}
        checkContrast
        disabled={locked}
        disabledMessage={disabledMessage}
        onChange={(value) => onChange({ primary_color: value ?? "" })}
      />
      <ColorField
        label={t("widget_admin_header_color")}
        description={t("widget_admin_header_color_description")}
        value={theme.header_color ?? null}
        clearable
        checkTextOn
        disabled={locked}
        disabledMessage={disabledMessage}
        onChange={(value) => onChange({ header_color: value })}
      />

      <div className="border-ax-border flex flex-col gap-4 rounded-lg border p-4">
        <Switch
          label={t("widget_admin_dark_mode_custom")}
          description={t("widget_admin_dark_mode_description")}
          value={showDark}
          isDisabled={locked}
          disabledMessage={disabledMessage}
          labelPosition="start"
          labelSpacing="spread"
          width="100%"
          onChange={toggleDark}
        />
        {showDark && (
          <div className="flex flex-col gap-6 pt-2">
            <ColorField
              label={t("widget_admin_primary_color_dark")}
              description={t("widget_admin_primary_color_dark_description")}
              value={theme.primary_color_dark ?? null}
              clearable
              checkContrast
              surface="dark"
              disabled={locked}
              disabledMessage={disabledMessage}
              onChange={(value) => onChange({ primary_color_dark: value })}
            />
            <ColorField
              label={t("widget_admin_header_color_dark")}
              description={t("widget_admin_header_color_dark_description")}
              value={theme.header_color_dark ?? null}
              clearable
              checkTextOn
              disabled={locked}
              disabledMessage={disabledMessage}
              onChange={(value) => onChange({ header_color_dark: value })}
            />
          </div>
        )}
      </div>

      <hr className="border-ax-border" />

      <div className="grid gap-6 sm:grid-cols-2">
        <Selector
          label={t("widget_admin_color_scheme")}
          description={t("widget_admin_color_scheme_description")}
          options={[
            { value: "auto", label: t("widget_admin_scheme_auto") },
            { value: "light", label: t("widget_admin_scheme_light") },
            { value: "dark", label: t("widget_admin_scheme_dark") }
          ]}
          value={theme.color_scheme ?? "auto"}
          onChange={(value) =>
            onChange({ color_scheme: value as NonNullable<WidgetTheme["color_scheme"]> })
          }
          isDisabled={locked}
          disabledMessage={disabledMessage}
          width="100%"
        />
        <Selector
          label={t("widget_admin_position")}
          description={t("widget_admin_position_description")}
          options={[
            { value: "bottom-right", label: t("widget_admin_position_right") },
            { value: "bottom-left", label: t("widget_admin_position_left") }
          ]}
          value={theme.position ?? "bottom-right"}
          onChange={(value) =>
            onChange({ position: value as NonNullable<WidgetTheme["position"]> })
          }
          isDisabled={locked}
          disabledMessage={disabledMessage}
          width="100%"
        />
        <NumberInput
          label={t("widget_admin_radius")}
          description={t("widget_admin_radius_description")}
          value={theme.radius ?? 12}
          min={0}
          max={24}
          step={1}
          isIntegerOnly
          units="px"
          isDisabled={locked}
          disabledMessage={disabledMessage}
          onChange={(value) => {
            if (value !== null && Number.isInteger(value)) {
              onChange({ radius: Math.min(24, Math.max(0, value)) });
            }
          }}
        />
      </div>
    </div>
  );
}
