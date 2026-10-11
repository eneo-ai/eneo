import { describe, expect, it } from "vitest";
import { m } from "$lib/paraglide/messages";

import {
  buildFlowRunBlockers,
  buildFlowRunReviewSummary,
  buildFlowRunWizardPages
} from "./flowRunWizard";

describe("flowRunWizard", () => {
  it("builds wizard pages in overview, form, runtime-step, and review order", () => {
    const pages = buildFlowRunWizardPages({
      hasTemplateOverview: true,
      hasFormFields: true,
      hasFreeformTextInput: false,
      stepsRequiringInput: [
        {
          step_id: "step-6",
          step_order: 6,
          label: "Indata denivorum",
          required: true,
          input_format: "document",
          accepted_mimetypes: []
        },
        {
          step_id: "step-7",
          step_order: 7,
          label: "Indata dilara",
          required: false,
          input_format: "audio",
          accepted_mimetypes: []
        }
      ]
    });

    expect(
      pages.map((page) => ({
        id: page.id,
        kind: page.kind,
        stepOrder: page.stepOrder,
        title: page.title
      }))
    ).toEqual([
      {
        id: "overview",
        kind: "overview",
        stepOrder: null,
        title: m.flow_run_wizard_overview_title()
      },
      { id: "form", kind: "form", stepOrder: null, title: m.flow_run_wizard_form_title() },
      {
        id: "runtime-step:step-6",
        kind: "runtime-step",
        stepOrder: 6,
        title: m.flow_run_wizard_runtime_step_title({ order: "6" })
      },
      {
        id: "runtime-step:step-7",
        kind: "runtime-step",
        stepOrder: 7,
        title: m.flow_run_wizard_runtime_step_title({ order: "7" })
      },
      { id: "review", kind: "review", stepOrder: null, title: m.flow_run_wizard_review_title() }
    ]);
  });

  it("skips empty sections and keeps a freeform page for legacy text-input flows", () => {
    const pages = buildFlowRunWizardPages({
      hasTemplateOverview: false,
      hasFormFields: false,
      hasFreeformTextInput: true,
      stepsRequiringInput: []
    });

    expect(pages.map((page) => page.kind)).toEqual(["freeform", "review"]);
    expect(pages[0]?.title).toBe(m.flow_run_wizard_freeform_title());
  });

  it("creates blockers for missing required files and required form fields with direct page targets", () => {
    const blockers = buildFlowRunBlockers({
      missingRequiredFieldNames: ["ämne"],
      stepsRequiringInput: [
        {
          step_id: "step-6",
          step_order: 6,
          label: "Indata denivorum",
          required: true,
          input_format: "document",
          accepted_mimetypes: []
        }
      ],
      runtimeFilesByStepId: {},
      templateReadinessItems: [],
      uploadingStepIds: []
    });

    expect(blockers).toEqual([
      {
        id: "form:ämne",
        kind: "missing-form-field",
        pageId: "form",
        title: m.flow_run_wizard_missing_form_field({ name: "ämne" }),
        actionLabel: m.flow_run_wizard_go_to_form(),
        blocksProgress: true
      },
      {
        id: "runtime-step:step-6",
        kind: "missing-runtime-input",
        pageId: "runtime-step:step-6",
        title: m.flow_run_wizard_missing_runtime_input({ order: "6", label: "Indata denivorum" }),
        actionLabel: m.flow_run_wizard_go_to_step({ order: "6" }),
        blocksProgress: true
      }
    ]);
  });

  it("treats uploads in progress as run blockers without trapping next-step navigation", () => {
    const blockers = buildFlowRunBlockers({
      missingRequiredFieldNames: [],
      stepsRequiringInput: [
        {
          step_id: "step-7",
          step_order: 7,
          label: "Ljudfil",
          required: false,
          input_format: "audio",
          accepted_mimetypes: []
        }
      ],
      runtimeFilesByStepId: {},
      templateReadinessItems: [],
      uploadingStepIds: ["step-7"]
    });

    expect(blockers).toEqual([
      {
        id: "uploading:step-7",
        kind: "upload-in-progress",
        pageId: "runtime-step:step-7",
        title: m.flow_run_wizard_upload_in_progress({ order: "7", label: "Ljudfil" }),
        actionLabel: m.flow_run_wizard_go_to_step({ order: "7" }),
        blocksProgress: false
      }
    ]);
  });

  it("blocks run submission while a browser recording is still active", () => {
    const blockers = buildFlowRunBlockers({
      missingRequiredFieldNames: [],
      stepsRequiringInput: [
        {
          step_id: "step-7",
          step_order: 7,
          label: "Ljudfil",
          required: false,
          input_format: "audio",
          accepted_mimetypes: []
        }
      ],
      runtimeFilesByStepId: {},
      templateReadinessItems: [],
      uploadingStepIds: [],
      recordingStepIds: ["step-7"]
    });

    expect(blockers).toEqual([
      {
        id: "recording:step-7",
        kind: "recording-in-progress",
        pageId: "runtime-step:step-7",
        title: m.flow_run_wizard_recording_in_progress({ order: "7", label: "Ljudfil" }),
        actionLabel: m.flow_run_wizard_go_to_step({ order: "7" }),
        blocksProgress: true
      }
    ]);
  });

  it("blocks progression when a stopped browser recording is still only local", () => {
    const blockers = buildFlowRunBlockers({
      missingRequiredFieldNames: [],
      stepsRequiringInput: [
        {
          step_id: "step-7",
          step_order: 7,
          label: "Ljudfil",
          required: false,
          input_format: "audio",
          accepted_mimetypes: []
        }
      ],
      runtimeFilesByStepId: {},
      localRecordingStepIds: ["step-7"],
      templateReadinessItems: [],
      uploadingStepIds: []
    });

    expect(blockers).toEqual([
      {
        id: "local-recording:step-7",
        kind: "local-recording-pending",
        pageId: "runtime-step:step-7",
        title: m.flow_run_wizard_local_recording_pending({ order: "7", label: "Ljudfil" }),
        actionLabel: m.flow_run_wizard_go_to_step({ order: "7" }),
        blocksProgress: true
      }
    ]);
  });

  it("builds compact review summary chips for templates, fields, steps, and files", () => {
    const summary = buildFlowRunReviewSummary({
      templateCount: 1,
      filledFieldCount: 2,
      runtimeStepCountWithFiles: 2,
      uploadedFileCount: 3
    });

    expect(summary).toEqual([
      { id: "templates", label: m.flow_run_wizard_summary_templates_one() },
      { id: "fields", label: m.flow_run_wizard_summary_fields({ count: "2" }) },
      { id: "steps", label: m.flow_run_wizard_summary_steps({ count: "2" }) },
      { id: "files", label: m.flow_run_wizard_summary_files({ count: "3" }) }
    ]);
  });

  it("says one field, one step and one file in the singular", () => {
    const summary = buildFlowRunReviewSummary({
      templateCount: 2,
      filledFieldCount: 1,
      runtimeStepCountWithFiles: 1,
      uploadedFileCount: 1
    });

    expect(summary.map((item) => item.label)).toEqual([
      m.flow_run_wizard_summary_templates({ count: "2" }),
      m.flow_run_wizard_summary_fields_one(),
      m.flow_run_wizard_summary_steps_one(),
      m.flow_run_wizard_summary_files_one()
    ]);
  });

  it("names a step without a label by its number in the reader's language", () => {
    const pages = buildFlowRunWizardPages({
      hasTemplateOverview: false,
      hasFormFields: false,
      hasFreeformTextInput: false,
      stepsRequiringInput: [
        {
          step_id: "step-2",
          step_order: 2,
          label: null,
          required: true,
          input_format: "document",
          accepted_mimetypes: []
        }
      ]
    });

    expect(pages[0]).toMatchObject({
      stepLabel: m.flow_step_fallback_label({ order: "2" })
    });
  });

  it("does not show a step id where a template has no name", () => {
    const blockers = buildFlowRunBlockers({
      missingRequiredFieldNames: [],
      stepsRequiringInput: [],
      runtimeFilesByStepId: {},
      templateReadinessItems: [
        { step_id: "3f2a9c1b", status: "needs_action", template_name: null }
      ],
      uploadingStepIds: []
    });

    expect(blockers[0]?.title).toBe(m.flow_run_wizard_template_not_ready_unnamed());
  });
});
