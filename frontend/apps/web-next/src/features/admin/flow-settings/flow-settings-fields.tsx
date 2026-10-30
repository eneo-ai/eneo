"use client";

import { Collapsible } from "@astryxdesign/core/Collapsible";
import { NumberInput } from "@astryxdesign/core/NumberInput";
import { Section } from "@astryxdesign/core/Section";
import { Heading, Text } from "@astryxdesign/core/Text";
import { useTranslations } from "use-intl";
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
 * One group of settings: an Astryx Section with the group's h2 and its
 * one-line summary, then its fields. `id` is the anchor the old admin URLs
 * and the save errors scroll to. Like the page's other groups it is not a
 * landmark: the h2 is what a screen reader lists.
 */
export function SettingsSection({
  id,
  title,
  description,
  children
}: {
  id: string;
  title: string;
  description: string;
  children: ReactNode;
}) {
  return (
    <Section
      id={id}
      padding={5}
      className="border-ax-border rounded-ax-container scroll-mt-32 overflow-hidden border"
    >
      <div className="flex flex-col gap-6">
        <div className="border-ax-border flex flex-col gap-1 border-b pb-4">
          <Heading level={2} className="text-base">
            {title}
          </Heading>
          <Text type="supporting" size="sm" as="p" display="block" className="m-0">
            {description}
          </Text>
        </div>
        {children}
      </div>
    </Section>
  );
}

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
          <Text size="sm" weight="medium">
            {title}
          </Text>
          <Text type="supporting" size="sm">
            {summary}
          </Text>
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
