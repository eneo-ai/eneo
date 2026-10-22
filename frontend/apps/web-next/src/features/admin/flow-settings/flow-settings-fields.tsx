"use client";

import { Collapsible } from "@astryxdesign/core/Collapsible";
import { NumberInput } from "@astryxdesign/core/NumberInput";
import { useTranslations } from "next-intl";
import type { ReactNode } from "react";
import type {
  FieldKey,
  FlowSettings,
  FlowSettingsDraft,
  NumberBounds,
  NumberKey
} from "./flow-settings";

/** What every section needs to show and change its fields. */
export type FieldKit = {
  draft: FlowSettingsDraft;
  /** The settings as the server last resolved them: facts and dynamic bounds. */
  settings: FlowSettings;
  bounds: { [Key in NumberKey]: NumberBounds };
  /** A save or restore is running: fields wait. */
  disabled: boolean;
  /** The problem to show at a field, or null. */
  problem: (key: FieldKey) => string | null;
  set: <Key extends FieldKey>(key: Key, value: FlowSettingsDraft[Key]) => void;
  /** Ref for a control (a field key, or another name), so focus can move to it. */
  fieldRef: (key: string) => (element: HTMLElement | null) => void;
};

/**
 * One number setting: an Astryx NumberInput in the units it is shown in
 * (minutes, kB), stored in API units. A value outside the bounds is brought
 * to the nearest bound when the field is left, as NumberInput does; an
 * empty clearable field sends null, which restores the default.
 */
export function SettingNumberField({
  kit,
  field,
  label,
  description,
  units,
  placeholder,
  disabledMessage
}: {
  kit: FieldKit;
  field: NumberKey;
  label: string;
  description: string;
  units?: string;
  placeholder?: string;
  disabledMessage?: string;
}) {
  const bounds = kit.bounds[field];
  const value = kit.draft[field];
  const problem = kit.problem(field);
  const toApi = (next: number) => Math.round(next * bounds.scale);
  const common = {
    label,
    description,
    units,
    placeholder,
    value: value === null ? null : value / bounds.scale,
    min: bounds.min / bounds.scale,
    max: bounds.max === null ? null : bounds.max / bounds.scale,
    isIntegerOnly: true,
    isDisabled: kit.disabled || disabledMessage !== undefined,
    disabledMessage,
    status: problem ? { type: "error" as const, message: problem } : undefined,
    ref: kit.fieldRef(field)
  };
  return bounds.clearable ? (
    <NumberInput
      {...common}
      hasClear
      onChange={(next) => kit.set(field, next === null ? null : toApi(next))}
    />
  ) : (
    <NumberInput {...common} onChange={(next) => kit.set(field, toApi(next))} />
  );
}

/**
 * Settings most organisations never change, behind a disclosure that says
 * what they are set to. It stays open while one of its fields is changed or
 * has a problem, so nothing unsaved or wrong is hidden.
 */
export function AdvancedSettings({
  title,
  summary,
  isOpen,
  isPinnedOpen,
  onOpenChange,
  children
}: {
  title: string;
  summary: string;
  isOpen: boolean;
  isPinnedOpen: boolean;
  onOpenChange: (open: boolean) => void;
  children: ReactNode;
}) {
  return (
    <Collapsible
      isOpen={isOpen || isPinnedOpen}
      onOpenChange={(open) => {
        if (open || !isPinnedOpen) onOpenChange(open);
      }}
      trigger={
        <span className="flex min-w-0 flex-col text-left">
          <span className="text-sm font-medium">{title}</span>
          <span className="text-muted-foreground text-sm font-normal">{summary}</span>
        </span>
      }
    >
      <div className="grid gap-5 pt-4 md:grid-cols-2">{children}</div>
    </Collapsible>
  );
}

/** The "Högst 5 000." line most fields end with, and the default hint for clearable ones. */
export function useLimitDescription() {
  const t = useTranslations();
  return (max: string, clearable = true) =>
    [t("flow_admin_limit_max", { max }), clearable ? t("flow_admin_empty_restores_default") : null]
      .filter(Boolean)
      .join(" ");
}
