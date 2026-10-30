"use client";

import { Button } from "@astryxdesign/core/Button";
import { referenceAuditRows } from "@eneo/skill-instructions/audit";
import { referenceUri } from "@eneo/skill-instructions";
import { useState } from "react";
import { useTranslations } from "use-intl";
import type { Schema } from "@/lib/api/models";

export function DebugSkillReferences({
  evidence,
  toolCalls
}: {
  evidence: Schema<"SkillActivationEvidenceV3">;
  toolCalls: Schema<"ToolCallInfo">[];
}) {
  const t = useTranslations();
  const [visible, setVisible] = useState(50);
  const rows = referenceAuditRows(evidence, toolCalls);
  if (!rows.length) return null;
  return (
    <details className="border-ax-border rounded-ax-element border p-3">
      <summary className="cursor-pointer text-sm font-semibold">
        {t("skills_reference_audit_title")} ({rows.length})
      </summary>
      <p className="text-ax-text-secondary my-3 text-xs leading-5">
        {t("skills_reference_audit_hint")}
      </p>
      <ol className="flex flex-col gap-3">
        {rows.slice(0, visible).map((row) => (
          <li key={row.id} className="flex min-w-0 flex-col gap-1 text-sm">
            <p className="break-words">
              <strong>{row.source}</strong> → {row.label}
            </p>
            <p className="text-ax-text-secondary text-xs">
              {t(`skills_reference_audit_${row.state}`)}
              {row.callOrders.length > 0 &&
                ` · ${t("skills_reference_audit_calls", { calls: row.callOrders.join(", ") })}`}
            </p>
            <details className="text-ax-text-secondary text-xs">
              <summary className="cursor-pointer">{t("skills_reference_details")}</summary>
              <code className="break-all">{referenceUri(row.target)}</code>
            </details>
          </li>
        ))}
      </ol>
      {visible < rows.length && (
        <Button
          label={t("load_more")}
          variant="ghost"
          onClick={() => setVisible((count) => count + 50)}
        />
      )}
    </details>
  );
}
