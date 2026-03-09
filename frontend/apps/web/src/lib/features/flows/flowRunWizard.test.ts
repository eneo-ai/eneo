import { describe, expect, it } from "vitest";

import {
  buildFlowRunBlockers,
  buildFlowRunReviewSummary,
  buildFlowRunWizardPages
} from "./flowRunWizard";

describe("flowRunWizard", () => {
  it("builds wizard pages in overview, form, runtime-step, and review order", () => {
    const pages = buildFlowRunWizardPages({
      locale: "sv",
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
      { id: "overview", kind: "overview", stepOrder: null, title: "Översikt" },
      { id: "form", kind: "form", stepOrder: null, title: "Formulär" },
      { id: "runtime-step:step-6", kind: "runtime-step", stepOrder: 6, title: "Steg 6 i flödet" },
      { id: "runtime-step:step-7", kind: "runtime-step", stepOrder: 7, title: "Steg 7 i flödet" },
      { id: "review", kind: "review", stepOrder: null, title: "Granska och kör" }
    ]);
  });

  it("skips empty sections and keeps a freeform page for legacy text-input flows", () => {
    const pages = buildFlowRunWizardPages({
      locale: "sv",
      hasTemplateOverview: false,
      hasFormFields: false,
      hasFreeformTextInput: true,
      stepsRequiringInput: []
    });

    expect(pages.map((page) => page.kind)).toEqual(["freeform", "review"]);
    expect(pages[0]?.title).toBe("Indata");
  });

  it("creates blockers for missing required files and required form fields with direct page targets", () => {
    const blockers = buildFlowRunBlockers({
      locale: "sv",
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
        title: 'Fältet "ämne" behöver fyllas i.',
        actionLabel: "Gå till formulär",
        blocksProgress: true
      },
      {
        id: "runtime-step:step-6",
        kind: "missing-runtime-input",
        pageId: "runtime-step:step-6",
        title: "Ladda upp filer för steg 6: Indata denivorum.",
        actionLabel: "Gå till steg 6",
        blocksProgress: true
      }
    ]);
  });

  it("treats uploads in progress as run blockers without trapping next-step navigation", () => {
    const blockers = buildFlowRunBlockers({
      locale: "sv",
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
        title: "Filer laddas fortfarande upp för steg 7: Ljudfil.",
        actionLabel: "Gå till steg 7",
        blocksProgress: false
      }
    ]);
  });

  it("builds compact review summary chips for templates, fields, steps, and files", () => {
    const summary = buildFlowRunReviewSummary({
      locale: "sv",
      templateCount: 1,
      filledFieldCount: 2,
      runtimeStepCountWithFiles: 2,
      uploadedFileCount: 3
    });

    expect(summary).toEqual([
      { id: "templates", label: "1 mall klar" },
      { id: "fields", label: "2 fält ifyllda" },
      { id: "steps", label: "2 steg med uppladdat underlag" },
      { id: "files", label: "3 filer uppladdade" }
    ]);
  });
});
