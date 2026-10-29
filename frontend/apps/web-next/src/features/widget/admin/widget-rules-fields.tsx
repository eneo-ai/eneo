"use client";

import { NumberInput } from "@astryxdesign/core/NumberInput";
import { Selector } from "@astryxdesign/core/Selector";
import { TextArea } from "@astryxdesign/core/TextArea";
import { useLocale, useTranslations } from "next-intl";
import { useEffect, useState } from "react";
import { Switch } from "@/components/astryx/switch";
import { SettingsGroup } from "@/components/composites/settings-rows";
import type { AutosaveSnapshot, Widget, WidgetAutosave } from "./autosave";
import { blockerLabel } from "./blockers";
import { MAX_DAILY_TOKEN_BUDGET } from "./limits";
import { MAX_ALLOWED_ORIGINS, parseOrigins } from "./origins";
import type { WidgetPolicy } from "./queries";
import { useTextDraft } from "./use-text-draft";

type Status = { type: "error"; message: string } | undefined;

/** A whole number committed when the field is left; out of range stays in the field with an error. */
function RuleNumber({
  label,
  description,
  value,
  min,
  max,
  step,
  problem,
  onCommit,
  onRange
}: {
  label: string;
  description: string;
  value: number;
  min: number;
  max: number;
  step?: number;
  /** The server's or the policy's objection to the saved value. */
  problem?: string;
  onCommit: (value: number) => void;
  /** Told whether the field holds a value it cannot send. */
  onRange: (held: boolean) => void;
}) {
  const t = useTranslations();
  const locale = useLocale();
  const [rangeError, setRangeError] = useState<string | null>(null);
  useEffect(() => {
    onRange(rangeError !== null);
    return () => onRange(false);
  }, [rangeError, onRange]);
  const message = rangeError ?? problem;
  const status: Status = message ? { type: "error", message } : undefined;
  return (
    <NumberInput
      label={label}
      description={description}
      value={value}
      min={min}
      max={max}
      step={step ?? 1}
      isIntegerOnly
      status={status}
      onChange={(next) => {
        if (next === null || !Number.isInteger(next) || next < min || next > max) {
          setRangeError(
            t("widget_admin_value_out_of_range", {
              min: min.toLocaleString(locale === "sv" ? "sv-SE" : "en-US"),
              max: max.toLocaleString(locale === "sv" ? "sv-SE" : "en-US")
            })
          );
          return;
        }
        setRangeError(null);
        onCommit(next);
      }}
    />
  );
}

/** Where the widget may run and what it may cost: origins, limits, privacy, protection. */
export function WidgetRulesFields({
  autosave,
  state,
  policy
}: {
  autosave: WidgetAutosave;
  state: AutosaveSnapshot<Widget>;
  policy: WidgetPolicy | null;
}) {
  const t = useTranslations();
  const widget = state.widget;
  const blockers = widget.activation_blockers ?? [];
  const limits = (change: Partial<Widget["limits"]>) =>
    autosave.patch({ limits: { ...widget.limits, ...change } });
  const privacy = (change: Partial<Widget["privacy"]>) =>
    autosave.patch({ privacy: { ...widget.privacy, ...change } });
  // What is wrong with a field: the value the server refused, or the saved
  // value breaking the organisation's policy.
  const problem = (path: string, ...codes: string[]): string | undefined => {
    if (state.refusals[path]) return state.refusals[path];
    const code = codes.find((candidate) => blockers.includes(candidate));
    return code ? blockerLabel(code, t) : undefined;
  };
  const budgetMax = Math.min(
    policy?.max_daily_token_budget ?? MAX_DAILY_TOKEN_BUDGET,
    MAX_DAILY_TOKEN_BUDGET
  );
  // Each number field reports whether it holds a value it cannot send.
  const range = (key: string) => (held: boolean) => autosave.markDraft(`rule-${key}`, held);

  // The list is committed when the field is left, and only when every line
  // is an origin the API accepts; the text stays as typed until then.
  const savedOrigins = (widget.allowed_origins ?? []).join("\n");
  const origins = useTextDraft(savedOrigins, (text) => {
    const parsed = parseOrigins(text);
    return parsed.invalid.length === 0 && !parsed.tooMany ? parsed.origins.join("\n") : null;
  });
  const parsedOrigins = parseOrigins(origins.text);
  // A live widget must keep serving: the API refuses an empty list for it.
  const emptiedWhileActive =
    widget.status === "active" &&
    parsedOrigins.origins.length === 0 &&
    parsedOrigins.invalid.length === 0;
  const [originsTouched, setOriginsTouched] = useState(false);
  const originsProblem =
    originsTouched && parsedOrigins.invalid.length > 0
      ? t("widget_admin_origins_invalid", { origins: parsedOrigins.invalid.join(", ") })
      : originsTouched && parsedOrigins.tooMany
        ? t("widget_admin_origins_too_many", { max: MAX_ALLOWED_ORIGINS })
        : originsTouched && emptiedWhileActive
          ? blockerLabel("allowed_origins_empty", t)
          : state.refusals["allowed_origins"]
            ? state.refusals["allowed_origins"]
            : (widget.allowed_origins ?? []).length === 0
              ? blockerLabel("allowed_origins_empty", t)
              : undefined;
  // Lines that cannot be sent yet hold back the valid ones with them.
  const originsHeld =
    (parsedOrigins.invalid.length > 0 || parsedOrigins.tooMany || emptiedWhileActive) &&
    origins.text.trim() !== savedOrigins;
  useEffect(() => {
    autosave.markDraft("allowed_origins", originsHeld);
    return () => autosave.markDraft("allowed_origins", false);
  }, [autosave, originsHeld]);

  // An empty list held back only because the widget was live is sent once it
  // no longer is, not left in the field until it is edited again.
  const [emptiedHeld, setEmptiedHeld] = useState(false);
  const [wasActive, setWasActive] = useState(widget.status === "active");
  if ((widget.status === "active") !== wasActive) {
    setWasActive(widget.status === "active");
    if (emptiedHeld && widget.status !== "active" && widget.status !== "archived") {
      setEmptiedHeld(false);
      if (parsedOrigins.invalid.length === 0 && !parsedOrigins.tooMany) {
        autosave.patch({ allowed_origins: parsedOrigins.origins });
      }
    }
  }

  function commitOrigins() {
    origins.onBlur();
    setOriginsTouched(true);
    setEmptiedHeld(emptiedWhileActive);
    if (parsedOrigins.invalid.length > 0 || parsedOrigins.tooMany || emptiedWhileActive) return;
    if (parsedOrigins.origins.join("\n") !== savedOrigins) {
      autosave.patch({ allowed_origins: parsedOrigins.origins });
    }
  }

  const noneAllowed = policy ? policy.allow_bot_protection_none : true;
  const protectionProblem = problem("bot_protection", "bot_protection_none_not_allowed");

  return (
    <div className="grid gap-6">
      <SettingsGroup
        title={t("widget_admin_placement")}
        description={t("widget_admin_allowed_origins_description")}
      >
        <TextArea
          label={t("widget_admin_allowed_origins")}
          description={t("widget_admin_allowed_origins_help")}
          rows={3}
          placeholder={t("widget_admin_allowed_origins_placeholder")}
          value={origins.text}
          onChange={origins.setText}
          onFocus={origins.onFocus}
          onBlur={commitOrigins}
          status={originsProblem ? { type: "error", message: originsProblem } : undefined}
          hasSpellCheck={false}
          width="100%"
        />
      </SettingsGroup>

      <SettingsGroup
        title={t("widget_admin_limits")}
        description={t("widget_admin_limits_description")}
      >
        <div className="grid gap-6 sm:grid-cols-2">
          <RuleNumber
            label={t("widget_admin_daily_budget")}
            description={
              policy
                ? t("widget_admin_daily_budget_description_policy", {
                    max: policy.max_daily_token_budget.toLocaleString("sv-SE")
                  })
                : t("widget_admin_daily_budget_description")
            }
            value={widget.limits.daily_token_budget ?? 0}
            min={1000}
            max={budgetMax}
            step={1000}
            problem={problem("limits.daily_token_budget", "daily_token_budget_exceeds_policy")}
            onCommit={(value) => limits({ daily_token_budget: value })}
            onRange={range("budget")}
          />
          <RuleNumber
            label={t("widget_admin_messages_per_ip")}
            description={t("widget_admin_messages_per_ip_description")}
            value={widget.limits.messages_per_ip_hour ?? 0}
            min={1}
            max={1000}
            onCommit={(value) => limits({ messages_per_ip_hour: value })}
            onRange={range("ip-rate")}
          />
          <RuleNumber
            label={t("widget_admin_max_question_chars")}
            description={t("widget_admin_max_question_chars_description")}
            value={widget.limits.max_question_chars ?? 0}
            min={100}
            max={8000}
            step={100}
            onCommit={(value) => limits({ max_question_chars: value })}
            onRange={range("question-chars")}
          />
          <RuleNumber
            label={t("widget_admin_max_turns")}
            description={t("widget_admin_max_turns_description")}
            value={widget.limits.max_session_turns ?? 0}
            min={1}
            max={100}
            onCommit={(value) => limits({ max_session_turns: value })}
            onRange={range("turns")}
          />
        </div>
      </SettingsGroup>

      <SettingsGroup
        title={t("widget_admin_privacy")}
        description={t("widget_admin_privacy_description")}
      >
        <RuleNumber
          label={t("widget_admin_retention")}
          description={
            policy
              ? t("widget_admin_retention_description_policy", {
                  min: policy.min_retention_days,
                  max: policy.max_retention_days
                })
              : t("widget_admin_retention_description")
          }
          value={widget.privacy.retention_days ?? 0}
          min={policy?.min_retention_days ?? 0}
          max={policy?.max_retention_days ?? 3650}
          problem={problem(
            "privacy.retention_days",
            "retention_below_policy_minimum",
            "retention_above_policy_maximum"
          )}
          onCommit={(value) => privacy({ retention_days: value })}
          onRange={range("retention")}
        />
        <Switch
          label={t("widget_admin_store_feedback_text")}
          description={t("widget_admin_store_feedback_text_description")}
          value={widget.privacy.store_feedback_text ?? false}
          labelPosition="start"
          labelSpacing="spread"
          width="100%"
          onChange={(checked) => privacy({ store_feedback_text: checked })}
        />
      </SettingsGroup>

      <SettingsGroup
        title={t("widget_admin_protection")}
        description={t("widget_admin_bot_protection_description")}
      >
        <Selector
          label={t("widget_admin_bot_protection")}
          description={
            !noneAllowed && !protectionProblem
              ? t("widget_admin_blocker_bot_protection")
              : undefined
          }
          options={[
            { value: "altcha", label: t("widget_admin_bot_protection_altcha") },
            { value: "none", label: t("widget_admin_bot_protection_none"), disabled: !noneAllowed }
          ]}
          value={widget.bot_protection ?? "altcha"}
          onChange={(value) =>
            autosave.patch({ bot_protection: value as NonNullable<Widget["bot_protection"]> })
          }
          status={protectionProblem ? { type: "error", message: protectionProblem } : undefined}
          width="100%"
        />
      </SettingsGroup>
    </div>
  );
}
