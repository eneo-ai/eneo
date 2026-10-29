"use client";

import { DateInput } from "@astryxdesign/core/DateInput";
import { useTranslations } from "use-intl";
import { useState } from "react";
import { FieldProblem } from "@/components/composites/field-problem";
import { useClientTimeText } from "@/components/composites/client-time";
import { Label } from "@/components/ui/label";
import { RadioGroup, RadioGroupItem } from "@/components/ui/radio-group";
import { isoDate, type IsoDate } from "@/lib/calendar-date";
import { getDaysUntilExpiration } from "./expiration-utils";

const PRESETS = [
  { days: 7, key: "api_keys_exp_7_days" },
  { days: 30, key: "api_keys_exp_30_days" },
  { days: 90, key: "api_keys_exp_90_days" },
  { days: 365, key: "api_keys_exp_1_year" }
] as const;

type Choice = `${(typeof PRESETS)[number]["days"]}` | "custom" | "none";

const DAY_MS = 24 * 60 * 60 * 1000;

/**
 * `days` of elapsed time from now, as the backend counts a policy's maximum
 * (now + timedelta(days)): not calendar days, which run an hour longer
 * across a daylight saving change.
 */
function daysFromNow(days: number): Date {
  return new Date(Date.now() + days * DAY_MS);
}

/** The expiry `days` from now, as an instant. */
export function expiryInDays(days: number): string {
  return daysFromNow(days).toISOString();
}

/**
 * A picked day expires at its end, local time (the backend compares
 * expires_at in real time, so the key works through the chosen day), but
 * never later than the policy's maximum: the last allowed day ends then.
 */
function endOfDay(date: IsoDate, maxDays: number | null | undefined): string {
  const end = new Date(`${date}T23:59:59`);
  const latest = maxDays ? daysFromNow(maxDays) : null;
  return (latest && latest < end ? latest : end).toISOString();
}

function initialChoice(value: string | null): Choice {
  if (!value) return "none";
  const day = isoDate(new Date(value));
  const preset = PRESETS.find((option) => isoDate(daysFromNow(option.days)) === day);
  return preset ? `${preset.days}` : "custom";
}

/**
 * When a key expires: a preset (7, 30, 90 days, a year), a custom day, or no
 * expiry. The tenant policy shapes it: presets beyond `maxDays` are left out,
 * the day picker stops there, and "no expiry" is gone when `required`. Says
 * when the chosen expiry falls, and warns about a key that never expires.
 * Mounted while its dialog is open, so it starts from `value` each time.
 */
export function ExpirationPicker({
  id,
  value,
  onChange,
  maxDays,
  required = false,
  problem = null
}: {
  /** Makes the field ids unique on the page. */
  id: string;
  value: string | null;
  onChange: (value: string | null) => void;
  maxDays?: number | null;
  required?: boolean;
  /** The field's problem, shown once the form is submitted. */
  problem?: string | null;
}) {
  const t = useTranslations();
  const [choice, setChoice] = useState<Choice | "">(() =>
    required && !value ? "" : initialChoice(value)
  );
  const presets = PRESETS.filter((preset) => !maxDays || preset.days <= maxDays);
  const min = isoDate(daysFromNow(1));
  const max = maxDays ? isoDate(daysFromNow(maxDays)) : undefined;
  const expiresOn = useClientTimeText(value, "date_time");
  const daysLeft = getDaysUntilExpiration(value);
  const legendId = `${id}-legend`;

  function choose(next: Choice) {
    setChoice(next);
    if (next === "none") onChange(null);
    else if (next !== "custom") onChange(expiryInDays(Number(next)));
    else if (!value) {
      const month = isoDate(daysFromNow(30));
      onChange(endOfDay(max && max < month ? max : month, maxDays));
    }
  }

  return (
    <fieldset
      className="flex flex-col gap-3"
      aria-describedby={problem ? `${id}-problem` : undefined}
    >
      <legend id={legendId} className="mb-2 text-sm font-medium">
        {t("api_keys_expiration")}
      </legend>
      <RadioGroup
        value={choice}
        onValueChange={(next) => choose(next as Choice)}
        aria-labelledby={legendId}
        aria-invalid={problem ? true : undefined}
        className="flex flex-wrap gap-x-5 gap-y-3"
      >
        {presets.map((preset) => (
          <ChoiceItem key={preset.days} id={id} value={`${preset.days}`} label={t(preset.key)} />
        ))}
        <ChoiceItem id={id} value="custom" label={t("api_keys_exp_custom")} />
        {!required && <ChoiceItem id={id} value="none" label={t("api_keys_exp_no_expiration")} />}
      </RadioGroup>
      {choice === "custom" && (
        <DateInput
          label={t("api_keys_exp_date")}
          description={maxDays ? t("api_keys_exp_max_days", { days: maxDays }) : undefined}
          presentation="adaptive-bottom-sheet"
          weekStartsOn="mon"
          min={min}
          max={max}
          value={value ? isoDate(new Date(value)) : undefined}
          onChange={(next) => {
            if (next) onChange(endOfDay(next, maxDays));
          }}
        />
      )}
      {value ? (
        <p className="text-muted-foreground text-sm">
          {expiresOn ? t("api_keys_exp_expires_on", { date: expiresOn }) : null}
          {daysLeft !== null && daysLeft >= 0
            ? ` · ${daysLeft === 1 ? t("api_keys_exp_1_day_from_now") : t("api_keys_exp_days_from_now", { count: daysLeft })}`
            : null}
        </p>
      ) : choice === "none" ? (
        <div className="flex flex-col gap-1 text-sm">
          <p className="text-muted-foreground">{t("api_keys_exp_valid_until_revoked")}</p>
          <p className="text-ax-warning">{t("api_keys_exp_warning")}</p>
        </div>
      ) : null}
      {maxDays && choice !== "custom" ? (
        <p className="text-muted-foreground text-xs">
          {t("api_keys_exp_max_days", { days: maxDays })}
        </p>
      ) : null}
      <FieldProblem id={id} problem={problem} />
    </fieldset>
  );
}

function ChoiceItem({ id, value, label }: { id: string; value: string; label: string }) {
  const itemId = `${id}-${value}`;
  return (
    <div className="flex items-center gap-2">
      <RadioGroupItem id={itemId} value={value} />
      <Label htmlFor={itemId} className="font-normal">
        {label}
      </Label>
    </div>
  );
}
