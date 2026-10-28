"use client";

import { NumberInput } from "@astryxdesign/core/NumberInput";
import { useLocale, useTranslations } from "next-intl";
import { useEffect, useState } from "react";
import { Switch } from "@/components/astryx/switch";
import { SettingsGroup } from "@/components/composites/settings-rows";
import { Autosave } from "../autosave";
import { toastWidgetError } from "../errors";
import { MAX_DAILY_TOKEN_BUDGET } from "../limits";
import type { WidgetPolicy } from "../queries";
import { useAutosave } from "../use-widget-autosave";
import { widgetPolicyApi, type WidgetPolicyUpdate } from "./queries";

const MAX_RETENTION_DAYS = 3650;

type Status = { type: "error"; message: string } | undefined;

/**
 * The organisation's limits for every widget, saved as they are edited.
 * The number fields commit when left and clamp to their bounds, so what is
 * sent is always within range; the retention window is saved as a pair,
 * because the API refuses a minimum above the maximum, so a bound that
 * crosses the other stays in its field with an error until the pair is
 * valid, and fixing either bound settles both.
 */
export function WidgetPolicyForm({ policy: initial }: { policy: WidgetPolicy }) {
  const t = useTranslations();
  const locale = useLocale();
  const number = new Intl.NumberFormat(locale === "sv" ? "sv-SE" : "en-US");
  const { autosave, state } = useAutosave(
    () =>
      new Autosave<WidgetPolicy, WidgetPolicyUpdate>(initial, async (update) => {
        try {
          return await widgetPolicyApi.update(update);
        } catch (error) {
          toastWidgetError(error, t);
          throw error;
        }
      }),
    "widget-policy"
  );
  const policy = state.widget;

  const outOfRange = (min: number, max: number) =>
    t("widget_admin_value_out_of_range", { min: number.format(min), max: number.format(max) });

  // Both retention bounds are kept as typed until the pair is valid, then
  // saved together; null means "as saved".
  const [typed, setTyped] = useState<{ min: number | null; max: number | null }>({
    min: null,
    max: null
  });
  const [typedInvalid, setTypedInvalid] = useState<{ min: boolean; max: boolean }>({
    min: false,
    max: false
  });
  const bound = (side: "min" | "max") =>
    typed[side] ?? (side === "min" ? policy.min_retention_days : policy.max_retention_days);
  const retentionErrors: { min?: string; max?: string } = {};
  for (const side of ["min", "max"] as const) {
    if (typedInvalid[side]) retentionErrors[side] = outOfRange(0, MAX_RETENTION_DAYS);
  }
  if (!retentionErrors.min && !retentionErrors.max && bound("min") > bound("max")) {
    if (typed.min !== null && typed.max === null) {
      retentionErrors.min = t("widget_admin_retention_window_min", { max: String(bound("max")) });
    } else {
      retentionErrors.max = t("widget_admin_retention_window_max", { min: String(bound("min")) });
    }
  }
  const retentionHeld = !!retentionErrors.min || !!retentionErrors.max;

  function commitRetention(side: "min" | "max", value: number | null) {
    const invalid =
      value === null || !Number.isInteger(value) || value < 0 || value > MAX_RETENTION_DAYS;
    const nextTyped = { ...typed, [side]: value };
    const nextInvalid = { ...typedInvalid, [side]: invalid };
    setTyped(nextTyped);
    setTypedInvalid(nextInvalid);
    if (nextInvalid.min || nextInvalid.max) return;
    const min = nextTyped.min ?? policy.min_retention_days;
    const max = nextTyped.max ?? policy.max_retention_days;
    if (min > max) return;
    const update: WidgetPolicyUpdate = {};
    if (min !== policy.min_retention_days) update.min_retention_days = min;
    if (max !== policy.max_retention_days) update.max_retention_days = max;
    setTyped({ min: null, max: null });
    if (Object.keys(update).length > 0) autosave.patch(update);
  }

  // A crossed retention window stays in its fields; leaving the page asks first.
  useEffect(() => {
    autosave.markDraft("policy-retention", retentionHeld);
  }, [autosave, retentionHeld]);

  const status = (message: string | undefined): Status =>
    message ? { type: "error", message } : undefined;

  return (
    <SettingsGroup
      title={t("widget_admin_policy")}
      description={t("widget_admin_policy_description")}
    >
      <div className="grid gap-6 md:grid-cols-3">
        <NumberInput
          label={t("widget_admin_policy_max_budget")}
          description={t("widget_admin_policy_max_budget_description")}
          value={policy.max_daily_token_budget}
          min={1000}
          max={MAX_DAILY_TOKEN_BUDGET}
          step={1000}
          isIntegerOnly
          status={status(state.refusals["max_daily_token_budget"])}
          onChange={(next) => {
            if (next !== null) autosave.patch({ max_daily_token_budget: next });
          }}
        />
        <NumberInput
          label={t("widget_admin_policy_retention_min")}
          description={t("widget_admin_policy_retention_description")}
          value={bound("min")}
          min={0}
          max={MAX_RETENTION_DAYS}
          isIntegerOnly
          status={status(retentionErrors.min ?? state.refusals["min_retention_days"])}
          onChange={(next) => commitRetention("min", next)}
        />
        <NumberInput
          label={t("widget_admin_policy_retention_max")}
          description={t("widget_admin_policy_retention_description")}
          value={bound("max")}
          min={0}
          max={MAX_RETENTION_DAYS}
          isIntegerOnly
          status={status(retentionErrors.max ?? state.refusals["max_retention_days"])}
          onChange={(next) => commitRetention("max", next)}
        />
      </div>
      <Switch
        label={t("widget_admin_policy_allow_none")}
        description={t("widget_admin_policy_allow_none_description")}
        value={policy.allow_bot_protection_none}
        labelPosition="start"
        labelSpacing="spread"
        width="100%"
        onChange={(checked) => autosave.patch({ allow_bot_protection_none: checked })}
      />
    </SettingsGroup>
  );
}
