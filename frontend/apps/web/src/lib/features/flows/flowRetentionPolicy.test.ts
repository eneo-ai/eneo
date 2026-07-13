import { describe, expect, it } from "vitest";
import type { FlowRetentionImpactPreview } from "@eneo/eneo-js";

import {
  confirmationFromFlowRetentionPreview,
  formatFlowRetentionBytes,
  organizationRetentionChangeIsDestructive,
  parseFlowRetentionDays,
  retentionDaysChangeIsDestructive
} from "./flowRetentionPolicy";

describe("Flow retention policy control-plane helpers", () => {
  it("parses Off and the exact 1..2555 day range", () => {
    expect(parseFlowRetentionDays("")).toEqual({ ok: true, days: null });
    expect(parseFlowRetentionDays(" 1 ")).toEqual({ ok: true, days: 1 });
    expect(parseFlowRetentionDays("2555")).toEqual({ ok: true, days: 2555 });
    expect(parseFlowRetentionDays("1.5")).toEqual({ ok: false, reason: "integer" });
    expect(parseFlowRetentionDays("0")).toEqual({ ok: false, reason: "out_of_range" });
    expect(parseFlowRetentionDays("2556")).toEqual({ ok: false, reason: "out_of_range" });
  });

  it("requires confirmation only when enabling or shortening", () => {
    expect(retentionDaysChangeIsDestructive(null, 30)).toBe(true);
    expect(retentionDaysChangeIsDestructive(30, 14)).toBe(true);
    expect(retentionDaysChangeIsDestructive(30, 60)).toBe(false);
    expect(retentionDaysChangeIsDestructive(30, null)).toBe(false);
    expect(
      organizationRetentionChangeIsDestructive(
        {
          run_debug_evidence_days: 7,
          flow_run_history_retention_days: 30,
          flow_runtime_upload_abandonment_days: null,
          effective_state: {
            run_history_deletion_active: true,
            runtime_upload_abandonment_active: false,
            classification_policy_count: 0
          }
        },
        60,
        14
      )
    ).toBe(true);
  });

  it("copies exact CAS evidence and formats impact bytes", () => {
    const emptyImpact = {
      current_eligible_count: 0,
      proposed_eligible_count: 0,
      newly_eligible_count: 0,
      no_longer_eligible_count: 0,
      proposed_eligible_bytes: 0,
      newly_eligible_bytes: 0,
      earliest_proposed_anchor: null,
      latest_proposed_anchor: null
    };
    const preview: FlowRetentionImpactPreview = {
      destructive_change: true,
      control_plane_version: "a".repeat(64),
      preview_hash: "b".repeat(64),
      previewed_at: "2026-07-13T12:00:00Z",
      run_history_anchor: "finished_at_or_created_at",
      runtime_upload_anchor: "created_at",
      run_history: emptyImpact,
      runtime_uploads: emptyImpact,
      lifecycle_blockers: {
        undelivered_audit_count: 0,
        unresolved_webhook_count: 0,
        active_rerun_count: 0
      },
      latent_space_retention_days: [],
      latent_flow_retention_days: []
    };
    expect(confirmationFromFlowRetentionPreview(preview)).toEqual({
      expected_control_plane_version: preview.control_plane_version,
      expected_preview_hash: preview.preview_hash,
      previewed_at: preview.previewed_at
    });
    expect(formatFlowRetentionBytes(0)).toBe("0 B");
    expect(formatFlowRetentionBytes(1536)).toBe("1.5 KiB");
    expect(formatFlowRetentionBytes(2 * 1024 ** 2)).toBe("2.0 MiB");
  });
});
