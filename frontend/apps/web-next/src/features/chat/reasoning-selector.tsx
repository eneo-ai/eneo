"use client";

import { Selector, type SelectorOptionType } from "@astryxdesign/core/Selector";
import { Brain } from "lucide-react";
import { useTranslations } from "next-intl";
import { useState } from "react";
import { effectiveReasoningEffort, reasoningEffortLabel } from "./reasoning-effort";

const DEFAULT_VALUE = "default";
const VALUE_PREFIX = "reasoning:";

export type ReasoningEffortSelectorProps = {
  /** The levels the current model offers (reasoningEffortOptions). */
  options: string[];
  /** The level stored on the assistant, if any. */
  stored: string | null;
  /** The organisation policy's default level, if any. */
  policyDefault: string | null;
  /**
   * Saves a level, or null for the organisation default. Return the save's
   * promise to show the new level while it saves; a rejected save falls back
   * to `stored`, so report the failure yourself.
   */
  onSelect: (effort: string | null) => void | Promise<unknown>;
  className?: string;
};

/**
 * The composer's reasoning-effort picker (Astryx Selector, ghost like the
 * model picker beside it): the organisation default (with the policy's level
 * named) and the levels the model offers. The trigger shows the level in
 * force and is named by it ("Resonemangsnivå: Hög").
 */
export function ReasoningEffortSelector({
  options,
  stored,
  policyDefault,
  onSelect,
  className
}: ReasoningEffortSelectorProps) {
  const t = useTranslations();
  const [pending, setPending] = useState<string | null>(null);
  const label = t("reasoning_effort");

  const storedValue =
    stored && options.includes(stored) ? `${VALUE_PREFIX}${stored}` : DEFAULT_VALUE;
  const value = pending ?? storedValue;
  const shownStored = value === DEFAULT_VALUE ? null : value.slice(VALUE_PREFIX.length);
  const effective = effectiveReasoningEffort({ stored: shownStored, policyDefault, options });
  const effectiveText = effective ? reasoningEffortLabel(effective, t) : t("default_behavior");
  const policyLabel =
    policyDefault && options.includes(policyDefault)
      ? reasoningEffortLabel(policyDefault, t)
      : undefined;

  const selectorOptions: SelectorOptionType[] = [
    {
      type: "section",
      title: label,
      options: [
        {
          value: DEFAULT_VALUE,
          label: t("governance_reasoning_organization_default"),
          description: policyLabel
        },
        ...options.map((option) => ({
          value: `${VALUE_PREFIX}${option}`,
          label: reasoningEffortLabel(option, t)
        }))
      ]
    }
  ];

  return (
    <Selector
      label={label}
      isLabelHidden
      // The trigger is named by its label alone: include the level in force.
      aria-label={t("reasoning_effort_value", { value: effectiveText })}
      variant="ghost"
      size="md"
      presentation="adaptive"
      startIcon={Brain}
      options={selectorOptions}
      value={value}
      isLoading={pending !== null}
      renderValue={() => <span className="block truncate max-[359px]:hidden">{effectiveText}</span>}
      onChange={(next) => {
        if (next === value) return;
        setPending(next);
        const effort = next.startsWith(VALUE_PREFIX) ? next.slice(VALUE_PREFIX.length) : null;
        void Promise.resolve(onSelect(effort))
          // The caller reports a failed save; the trigger shows `stored` again.
          .catch(() => {})
          .finally(() => setPending((current) => (current === next ? null : current)));
      }}
      className={className}
    />
  );
}
