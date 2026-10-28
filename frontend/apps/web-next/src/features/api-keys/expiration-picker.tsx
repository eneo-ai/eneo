"use client";

import { DateInput, type DateInputProps } from "@astryxdesign/core/DateInput";
import { useTranslations } from "next-intl";
import { useState } from "react";
import { FieldProblem } from "@/components/composites/field-problem";
import { useClientTimeText } from "@/components/composites/client-time";
import { Label } from "@/components/ui/label";
import { RadioGroup, RadioGroupItem } from "@/components/ui/radio-group";
import { getDaysUntilExpiration } from "./expiration-utils";

type IsoDate = NonNullable<DateInputProps["value"]>;

const PRESETS = [
  { days: 7, key: "api_keys_exp_7_days" },
  { days: 30, key: "api_keys_exp_30_days" },
  { days: 90, key: "api_keys_exp_90_days" },
  { days: 365, key: "api_keys_exp_1_year" }
] as const;

type Choice = `${(typeof PRESETS)[number]["days"]}` | "custom" | "none";

/** A local calendar date as YYYY-MM-DD. */
function localDate(date: Date): IsoDate {
  const month = String(date.getMonth() + 1).padStart(2, "0");
  const day = String(date.getDate()).padStart(2, "0");
  return `${date.getFullYear()}-${month}-${day}` as IsoDate;
}

function daysFromNow(days: number): Date {
  const date = new Date();
  date.setDate(date.getDate() + days);
  return date;
}

/** The expiry `days` from now, as an instant. */
export function expiryInDays(days: number): string {
  return daysFromNow(days).toISOString();
}

/**
 * A picked day expires at its end, local time: the backend compares expires_at
 * in real time, so 23:59:59 keeps the key usable through the chosen day.
 */
function endOfDay(date: IsoDate): string {
  return new Date(`${date}T23:59:59`).toISOString();
}

function initialChoice(value: string | null): Choice {
  if (!value) return "none";
  const day = localDate(new Date(value));
  const preset = PRESETS.find((option) => localDate(daysFromNow(option.days)) === day);
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
  const min = localDate(daysFromNow(1));
  const max = maxDays ? localDate(daysFromNow(maxDays)) : undefined;
  const expiresOn = useClientTimeText(value, "date_time");
  const daysLeft = getDaysUntilExpiration(value);
  const legendId = `${id}-legend`;

  function choose(next: Choice) {
    setChoice(next);
    if (next === "none") onChange(null);
    else if (next !== "custom") onChange(expiryInDays(Number(next)));
    else if (!value) {
      const month = localDate(daysFromNow(30));
      onChange(endOfDay(max && max < month ? max : month));
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
          value={value ? localDate(new Date(value)) : undefined}
          onChange={(next) => {
            if (next) onChange(endOfDay(next));
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
