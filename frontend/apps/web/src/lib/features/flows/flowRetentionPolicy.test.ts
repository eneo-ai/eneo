// @vitest-environment jsdom

import { render } from "@testing-library/svelte";
import { describe, expect, it, vi } from "vitest";
import type { FlowRetentionImpactPreview } from "@eneo/eneo-js";

import FlowRetentionImpactDialog from "./components/FlowRetentionImpactDialog.svelte";
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
          flow_run_history_minimum_retention_days: null,
          flow_run_history_no_purge: false,
          flow_runtime_upload_abandonment_days: null,
          effective_state: {
            run_history_deletion_active: true,
            runtime_upload_abandonment_active: false,
            classification_policy_count: 0,
            activation_sources: ["organization"],
            barrier_sources: []
          }
        },
        60,
        14,
        null,
        false
      )
    ).toBe(true);
    expect(
      organizationRetentionChangeIsDestructive(
        {
          run_debug_evidence_days: 7,
          flow_run_history_retention_days: null,
          flow_run_history_minimum_retention_days: null,
          flow_run_history_no_purge: false,
          flow_runtime_upload_abandonment_days: null,
          effective_state: {
            run_history_deletion_active: false,
            runtime_upload_abandonment_active: false,
            classification_policy_count: 0,
            activation_sources: [],
            barrier_sources: []
          }
        },
        null,
        null,
        90,
        false
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
      latest_proposed_anchor: null,
      earliest_proposed_delete_after_at: null,
      latest_proposed_delete_after_at: null,
      earliest_proposed_minimum_not_before_at: null,
      latest_proposed_minimum_not_before_at: null
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
      policy_blockers: {
        run_history_minimum_not_satisfied_count: 0,
        run_history_no_purge_count: 0,
        run_history_policy_conflict_count: 0,
        runtime_upload_minimum_not_satisfied_count: 0,
        runtime_upload_no_purge_count: 0,
        runtime_upload_policy_conflict_count: 0
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

  it("renders current, proposed, newly eligible, and no-longer-eligible counts", () => {
    const impact = {
      current_eligible_count: 11,
      proposed_eligible_count: 7,
      newly_eligible_count: 3,
      no_longer_eligible_count: 4,
      proposed_eligible_bytes: 1024,
      newly_eligible_bytes: 512,
      earliest_proposed_anchor: null,
      latest_proposed_anchor: null,
      earliest_proposed_delete_after_at: null,
      latest_proposed_delete_after_at: null,
      earliest_proposed_minimum_not_before_at: null,
      latest_proposed_minimum_not_before_at: null
    };
    const preview: FlowRetentionImpactPreview = {
      destructive_change: true,
      control_plane_version: "a".repeat(64),
      preview_hash: "b".repeat(64),
      previewed_at: "2026-07-15T12:00:00Z",
      run_history_anchor: "finished_at_or_created_at",
      runtime_upload_anchor: "created_at",
      run_history: impact,
      runtime_uploads: impact,
      lifecycle_blockers: {
        undelivered_audit_count: 0,
        unresolved_webhook_count: 0,
        active_rerun_count: 0
      },
      policy_blockers: {
        run_history_minimum_not_satisfied_count: 0,
        run_history_no_purge_count: 0,
        run_history_policy_conflict_count: 0,
        runtime_upload_minimum_not_satisfied_count: 0,
        runtime_upload_no_purge_count: 0,
        runtime_upload_policy_conflict_count: 0
      },
      latent_space_retention_days: [],
      latent_flow_retention_days: []
    };

    render(FlowRetentionImpactDialog, {
      preview,
      open: true,
      onConfirm: vi.fn()
    });

    expect(document.body.textContent).toContain("11");
    expect(document.body.textContent).toContain("7");
    expect(document.body.textContent).toContain("3");
    expect(document.body.textContent).toContain("4");
  });
});
