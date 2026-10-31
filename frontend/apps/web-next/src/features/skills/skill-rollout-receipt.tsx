import { proportional, type TableColumn } from "@astryxdesign/core/Table";
import { useAnnounce } from "@astryxdesign/core/hooks";
import { useEffect, useId } from "react";
import { useTranslations } from "use-intl";
import { Table } from "@/components/astryx/table";
import { ListError } from "@/components/composites/query-state";
import { Badge } from "@/components/ui/badge";
import type { RolloutPhase, RolloutProgress, RolloutReason } from "./skill-rollout";

const reasonLabels = {
  activation_unavailable: "organization_skills_rollout_activation_unavailable",
  context_window: "organization_skills_rollout_context_window",
  attachment_limit: "organization_skills_rollout_attachment_limit",
  conflicting_revisions: "organization_skills_rollout_conflicting_revisions"
} as const satisfies Record<RolloutReason, string>;
type Outcome = { id: string; label: string; count: number };

function PhaseReceipt({ phase, apps }: { phase: RolloutPhase; apps: boolean }) {
  const t = useTranslations();
  const headingId = useId();
  const reasons = Object.entries(reasonLabels).filter(
    ([reason]) => !apps || reason !== "activation_unavailable"
  );
  const rows: Outcome[] = [
    { id: "updated", label: t("organization_skills_rollout_updated"), count: phase.updated },
    {
      id: "concurrent",
      label: t("organization_skills_rollout_concurrent_change"),
      count: phase.concurrent
    },
    ...reasons.map(([reason, key]) => ({
      id: reason,
      label: t(key),
      count: phase.reasons[reason as RolloutReason] ?? 0
    }))
  ];
  const unnamed =
    phase.incompatible -
    Object.values(phase.reasons).reduce<number>((sum, count) => sum + (count ?? 0), 0);
  if (unnamed > 0)
    rows.push({
      id: "incompatible",
      label: t("organization_skills_rollout_incompatible"),
      count: unnamed
    });
  const columns: TableColumn<Outcome>[] = [
    {
      key: "label",
      header: t("organization_skills_rollout_outcome_column"),
      width: proportional(3)
    },
    {
      key: "count",
      header: t("organization_skills_rollout_count_column"),
      width: proportional(1),
      align: "end"
    }
  ];
  return (
    <section className="min-w-0 space-y-3 rounded-lg border p-3" aria-labelledby={headingId}>
      <div className="flex flex-wrap items-center gap-2">
        <h4 id={headingId} className="font-medium">
          {t(apps ? "organization_skills_rollout_apps_title" : "assistants")}
        </h4>
        <Badge variant={phase.status === "failed" ? "destructive" : "outline"}>
          {t(
            phase.status === "pending"
              ? "organization_skills_rollout_apps_status_pending"
              : `organization_skills_rollout_status_${phase.status}`
          )}
        </Badge>
      </div>
      <p className="font-medium tabular-nums">
        {t(
          apps
            ? "organization_skills_rollout_apps_progress"
            : "organization_skills_rollout_progress",
          { updated: String(phase.updated), total: String(phase.total) }
        )}
      </p>
      <Table
        data={rows}
        columns={columns}
        idKey="id"
        density="compact"
        aria-labelledby={headingId}
      />
      <p className="text-muted-foreground text-sm">
        {t(
          apps
            ? "organization_skills_rollout_apps_exclusions"
            : "organization_skills_rollout_exclusions"
        )}
      </p>
      {apps && (
        <p className="text-muted-foreground text-sm">
          {t("organization_skills_rollout_apps_queued_runs_unchanged")}
        </p>
      )}
      {phase.status === "failed" && (
        <ListError
          error={phase.error}
          title={t(
            apps
              ? "organization_skills_rollout_apps_failure"
              : "organization_skills_rollout_failure"
          )}
        />
      )}
    </section>
  );
}

export function SkillRolloutReceipt({ rollout }: { rollout: RolloutProgress }) {
  const t = useTranslations();
  const announce = useAnnounce();
  const progress = [
    rollout.assistants &&
      `${t("assistants")}: ${t("organization_skills_rollout_progress", { updated: String(rollout.assistants.updated), total: String(rollout.assistants.total) })}`,
    rollout.apps &&
      `${t("organization_skills_rollout_apps_title")}: ${t("organization_skills_rollout_apps_progress", { updated: String(rollout.apps.updated), total: String(rollout.apps.total) })}`
  ]
    .filter(Boolean)
    .join(". ");
  const announcement = rollout.stopRequested
    ? t("organization_skills_rollout_stop")
    : `${progress}. ${t(`organization_skills_rollout_status_${rollout.status}`)}`;
  useEffect(() => {
    announce(announcement);
  }, [announce, announcement]);
  return (
    <div className="space-y-3">
      <div className="grid gap-4 lg:grid-cols-2">
        {rollout.assistants && <PhaseReceipt phase={rollout.assistants} apps={false} />}
        {rollout.apps && <PhaseReceipt phase={rollout.apps} apps />}
      </div>
      {rollout.assistants && (
        <p className="text-muted-foreground text-sm">
          {t(`organization_skills_rollout_personal_chat_${rollout.personalChat}`)}
        </p>
      )}
    </div>
  );
}
