"use client";

import { Badge } from "@astryxdesign/core/Badge";
import { Banner } from "@astryxdesign/core/Banner";
import { Button } from "@astryxdesign/core/Button";
import { Collapsible } from "@astryxdesign/core/Collapsible";
import { ProgressBar } from "@astryxdesign/core/ProgressBar";
import { ChevronDown } from "lucide-react";
import { useFormatter, useTranslations } from "next-intl";
import { useState } from "react";
import { cn } from "@/lib/utils";
import { CopyableValue, DebugSection } from "./debug-section";
import {
  buildSkillActivationRows,
  summarizeSkillActivation,
  unmatchedActivationRejections,
  type SkillActivationEvidence,
  type SkillActivationRejection,
  type SkillActivationRow
} from "./turn-debug";

const PAGE_SIZE = 50;

type Translate = ReturnType<typeof useTranslations>;

const MODE_KEY = {
  eager: ["chat_debug_mode_eager", "chat_debug_mode_eager_description"],
  always_only: ["chat_debug_mode_always_only", "chat_debug_mode_always_only_description"],
  selective: ["chat_debug_mode_selective", "chat_debug_mode_selective_description"]
} as const satisfies Record<SkillActivationEvidence["effective_mode"], [string, string]>;

const FALLBACK_KEY = {
  model_lacks_tool_calling: "chat_debug_fallback_model_lacks_tool_calling",
  catalog_budget_exceeded: "chat_debug_fallback_catalog_budget_exceeded",
  token_measurement_unavailable: "chat_debug_fallback_token_measurement_unavailable",
  selective_activation_disabled: "chat_debug_fallback_selective_activation_disabled"
} as const satisfies Record<NonNullable<SkillActivationEvidence["fallback_reason"]>, string>;

const REJECTION_KEY = {
  unknown_key: "chat_debug_rejection_unknown_key",
  blocked: "chat_debug_rejection_blocked",
  activation_unavailable: "chat_debug_rejection_activation_unavailable",
  activation_limit_exceeded: "chat_debug_rejection_activation_limit_exceeded",
  context_limit_exceeded: "chat_debug_rejection_context_limit_exceeded",
  model_context_limit_exceeded: "chat_debug_rejection_model_context_limit_exceeded",
  token_measurement_unavailable: "chat_debug_rejection_token_measurement_unavailable",
  reserved_tool_collision: "chat_debug_rejection_reserved_tool_collision"
} as const satisfies Record<SkillActivationRejection["reason"], string>;

type Decision = { text: string; tone: "positive" | "destructive" | "muted" };

const DECISION_CLASS: Record<Decision["tone"], string> = {
  positive: "text-ax-success",
  destructive: "text-ax-error",
  muted: "text-ax-text-secondary"
};

/** What happened to one candidate, as lines of text (colour is never the only signal). */
function decisions(
  row: SkillActivationRow,
  mode: SkillActivationEvidence["effective_mode"],
  t: Translate
): Decision[] {
  const lines: Decision[] = [];
  if (row.candidateState === "blocked") {
    lines.push({ text: t("chat_debug_rejection_blocked"), tone: "destructive" });
  }
  for (const reason of row.rejectionReasons) {
    lines.push({
      text: `${t("chat_debug_outcome_rejected")}: ${t(REJECTION_KEY[reason])}`,
      tone: "destructive"
    });
  }
  if (row.outcomes.includes("accepted")) {
    lines.push({ text: t("chat_debug_activated_on_demand"), tone: "positive" });
  } else if (row.activationMode === "always") {
    lines.push({ text: t("chat_debug_initially_active"), tone: "positive" });
  }
  if (row.outcomes.includes("repeated")) {
    lines.push({ text: t("chat_debug_outcome_repeated"), tone: "muted" });
  }
  if (row.activationMode === "on_demand" && row.outcomes.length === 0) {
    lines.push({
      text:
        mode === "always_only"
          ? t("chat_debug_candidate_always_only")
          : t("chat_debug_candidate_not_called"),
      tone: "muted"
    });
  }
  return lines;
}

function outcomeBadge(row: SkillActivationRow, t: Translate) {
  if (row.candidateState === "blocked") {
    return <Badge variant="error" label={t("chat_debug_outcome_blocked")} />;
  }
  if (row.outcomes.includes("rejected")) {
    return <Badge variant="error" label={t("chat_debug_outcome_rejected")} />;
  }
  if (row.outcomes.includes("accepted") || row.activationMode === "always") {
    return <Badge variant="success" label={t("chat_debug_outcome_activated")} />;
  }
  return <Badge variant="neutral" label={t("chat_debug_outcome_available")} />;
}

function CandidateRow({
  row,
  mode
}: {
  row: SkillActivationRow;
  mode: SkillActivationEvidence["effective_mode"];
}) {
  const t = useTranslations();
  return (
    <li className="border-ax-border rounded-ax-element flex flex-col gap-2 border px-3 py-2.5">
      <div className="flex min-w-0 items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="text-sm leading-5 font-semibold break-words">
            {row.display_name ?? row.slug ?? row.skill_id}
          </p>
          <p className="text-ax-text-secondary text-xs leading-4 break-words">
            {[
              row.display_name && row.slug ? row.slug : null,
              t("chat_debug_candidate_position", { position: row.position + 1 }),
              t("chat_debug_revision", { number: row.revision_number }),
              row.source === "space"
                ? t("chat_debug_source_space")
                : t("chat_debug_source_organization")
            ]
              .filter((part): part is string => part !== null)
              .join(" · ")}
          </p>
        </div>
        <div className="flex shrink-0 flex-wrap justify-end gap-1.5">
          {row.activationMode === "always" && (
            <Badge variant="neutral" label={t("skills_activation_mode_always")} />
          )}
          {row.activationMode === "on_demand" && (
            <Badge variant="neutral" label={t("skills_activation_mode_on_demand")} />
          )}
          {outcomeBadge(row, t)}
        </div>
      </div>
      <ul className="flex flex-col gap-0.5 text-sm leading-5">
        {decisions(row, mode, t).map((decision, index) => (
          <li key={`${decision.text}:${index}`} className={DECISION_CLASS[decision.tone]}>
            {decision.text}
          </li>
        ))}
      </ul>
      <Collapsible trigger={t("chat_debug_technical_details")} defaultIsOpen={false}>
        <dl className="flex flex-col gap-2 pt-1">
          <CopyableValue label={t("chat_debug_skill_revision_id")} value={row.skill_revision_id} />
          <CopyableValue label={t("chat_debug_activation_key")} value={row.activationKey} />
          <CopyableValue label={t("chat_debug_digest")} value={row.content_digest} />
        </dl>
      </Collapsible>
    </li>
  );
}

/**
 * The Skill activation evidence of a turn: a verdict, the effective mode and
 * why a fallback applied, counts, the Skill token budget and every candidate
 * in evaluation order with what happened to it (50 at a time).
 */
export function SkillActivationSection({ evidence }: { evidence: SkillActivationEvidence }) {
  const t = useTranslations();
  const format = useFormatter();
  const [visibleCount, setVisibleCount] = useState(PAGE_SIZE);
  const rows = buildSkillActivationRows(evidence);
  const summary = summarizeSkillActivation(evidence);
  const unmatched = unmatchedActivationRejections(evidence);
  const number = (value: number) => format.number(value);

  const status =
    summary.blocked > 0 || summary.rejected > 0
      ? "warning"
      : summary.enteredContext > 0
        ? "activated"
        : "none";
  const verdict = [
    summary.available === 1
      ? t("chat_debug_verdict_available_one", { count: "1" })
      : t("chat_debug_verdict_available_other", { count: number(summary.available) }),
    summary.enteredContext === 1
      ? t("chat_debug_verdict_active_one", { count: "1" })
      : t("chat_debug_verdict_active_other", { count: number(summary.enteredContext) })
  ].join(" · ");
  // Nothing entered context and no fallback explains it: the model simply
  // never called the activation tool for its on-demand candidates.
  const nothingCalled =
    summary.enteredContext === 0 &&
    !evidence.fallback_reason &&
    evidence.effective_mode === "selective" &&
    rows.some((row) => row.activationMode === "on_demand");

  const stats: [string, string][] = [
    [t("chat_debug_available"), number(summary.available)],
    [t("chat_debug_entered_context"), number(summary.enteredContext)],
    [t("chat_debug_blocked"), number(summary.blocked)],
    [t("chat_debug_rejected"), number(summary.rejected)],
    ...(evidence.effective_mode === "selective"
      ? ([
          [t("chat_debug_rounds"), number(evidence.activation_rounds ?? 0)],
          [
            t("chat_debug_latency"),
            t("chat_debug_milliseconds", { count: evidence.selection_latency_ms ?? 0 })
          ]
        ] as [string, string][])
      : [])
  ];
  const [modeKey, modeDescriptionKey] = MODE_KEY[evidence.effective_mode];
  const visibleRows = rows.slice(0, visibleCount);
  const remaining = Math.max(0, rows.length - visibleCount);

  return (
    <DebugSection title={t("chat_debug_skill_activation")} count={rows.length}>
      <div className="flex flex-col gap-1.5">
        <div className="flex flex-wrap items-center justify-between gap-x-3 gap-y-1.5">
          <p className="text-sm font-semibold tabular-nums">{verdict}</p>
          {status === "activated" ? (
            <Badge variant="success" label={t("chat_debug_status_activated")} />
          ) : status === "warning" ? (
            <Badge variant="warning" label={t("chat_debug_status_warning")} />
          ) : (
            <Badge variant="neutral" label={t("chat_debug_status_none")} />
          )}
        </div>
        {nothingCalled && (
          <p className="text-ax-text-secondary text-sm leading-5">
            {t("chat_debug_reason_not_called")}
          </p>
        )}
        <p className="text-ax-text-secondary text-sm leading-5">
          <span className="text-ax-text font-medium">{t(modeKey)}.</span> {t(modeDescriptionKey)}
        </p>
      </div>

      {evidence.fallback_reason && (
        <Banner
          status="info"
          title={t("chat_debug_fallback_title")}
          description={t(FALLBACK_KEY[evidence.fallback_reason])}
        />
      )}

      <dl
        className={cn(
          "bg-ax-border rounded-ax-element grid gap-px overflow-hidden",
          stats.length > 4 ? "grid-cols-2 sm:grid-cols-3" : "grid-cols-2"
        )}
      >
        {stats.map(([label, value]) => (
          <div key={label} className="bg-ax-surface min-w-0 px-3 py-1.5">
            <dt className="text-ax-text-secondary truncate text-xs leading-4" title={label}>
              {label}
            </dt>
            <dd className="mt-0.5 text-sm font-semibold tabular-nums">{value}</dd>
          </div>
        ))}
      </dl>

      <ProgressBar
        label={t("chat_debug_token_budget")}
        value={Math.min(evidence.skill_context_tokens, evidence.skill_context_token_limit)}
        max={Math.max(evidence.skill_context_token_limit, 1)}
        hasValueLabel
        formatValueLabel={() =>
          [
            t("chat_debug_token_budget_of", {
              used: number(evidence.skill_context_tokens),
              limit: number(evidence.skill_context_token_limit)
            }),
            evidence.token_count_source !== "litellm"
              ? `(${t("chat_debug_token_source_fallback_estimate")})`
              : null
          ]
            .filter((part): part is string => part !== null)
            .join(" ")
        }
      />

      <div className="flex flex-col gap-2">
        <h4 className="text-sm font-semibold">{t("chat_debug_candidate_order")}</h4>
        {rows.length === 0 ? (
          <div className="flex flex-col gap-1 py-1">
            <p className="text-sm font-medium">{t("chat_debug_zero_skills_title")}</p>
            <p className="text-ax-text-secondary text-sm">
              {t("chat_debug_zero_skills_description")}
            </p>
          </div>
        ) : (
          <ol className="flex flex-col gap-2">
            {visibleRows.map((row) => (
              <CandidateRow key={row.skill_revision_id} row={row} mode={evidence.effective_mode} />
            ))}
          </ol>
        )}
        {remaining > 0 && (
          <Button
            className="self-start"
            variant="secondary"
            size="sm"
            icon={<ChevronDown aria-hidden="true" className="size-4" />}
            label={t("chat_debug_show_more", { count: Math.min(PAGE_SIZE, remaining) })}
            onClick={() => setVisibleCount((count) => count + PAGE_SIZE)}
          />
        )}
      </div>

      {unmatched.length > 0 && (
        <Banner status="error" title={t("chat_debug_unmatched_rejections")} collapsible={false}>
          <ul className="flex flex-col gap-2 text-sm">
            {unmatched.map((rejection, index) => (
              <li
                key={`${rejection.activation_key}:${rejection.reason}:${index}`}
                className="break-all"
              >
                <strong>{rejection.activation_key}</strong>: {t(REJECTION_KEY[rejection.reason])}
              </li>
            ))}
          </ul>
        </Banner>
      )}
    </DebugSection>
  );
}
