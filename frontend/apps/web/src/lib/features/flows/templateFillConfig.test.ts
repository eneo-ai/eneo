import { describe, expect, it } from "vitest";

import {
  applyAutoTemplateBindings,
  applyTemplateInspection,
  buildTemplateBindingAutoSuggestions,
  buildTemplateBindingSuggestions,
  createTemplateFillDraftConfig,
  getTemplateFillOutputConfig,
  getTemplateFillDryRunIssues,
  getTemplateFillReadiness,
  groupTemplateBindingSuggestions,
  isTemplateFillStep,
  listTemplateBindingRows,
  listTemplatePlaceholders,
  resolveTemplateAssetSelection,
  updateTemplateBinding
} from "./templateFillConfig";

const labels = {
  formField: "Form fields",
  aiSection: "AI sections",
  systemVariable: "System variables",
  formFieldItem: (name: string) => `Form field: ${name}`,
  stepTextItem: (stepLabel: string) => `${stepLabel} -> text`,
  stepJsonItem: (stepLabel: string) => `${stepLabel} -> json`,
  todayDate: "Today",
  leaveEmpty: "Leave empty",
  emptyValue: ""
};

describe("templateFillConfig", () => {
  it("recognizes template_fill steps", () => {
    expect(isTemplateFillStep({ output_mode: "template_fill" } as never)).toBe(true);
    expect(isTemplateFillStep({ output_mode: "pass_through" } as never)).toBe(false);
  });

  it("returns an empty config for invalid output_config payloads", () => {
    expect(getTemplateFillOutputConfig(null)).toEqual({});
    expect(getTemplateFillOutputConfig({ output_config: null } as never)).toEqual({});
    expect(getTemplateFillOutputConfig({ output_config: [] } as never)).toEqual({});
  });

  it("creates a draft-safe template config with default bindings and placeholders", () => {
    expect(createTemplateFillDraftConfig({})).toEqual({
      bindings: {},
      placeholders: []
    });
    expect(
      createTemplateFillDraftConfig({
        template_file_id: "file-1",
        bindings: { summary: "{{step_1.output.text}}" },
        placeholders: ["summary"]
      })
    ).toEqual({
      template_file_id: "file-1",
      bindings: { summary: "{{step_1.output.text}}" },
      placeholders: ["summary"]
    });
  });

  it("merges inspection placeholders into bindings without losing existing values", () => {
    const next = applyTemplateInspection(
      {
        template_file_id: "old-file",
        bindings: { summary: "{{step_1.output.text}}" }
      },
      {
        file_id: "new-file",
        file_name: "rapport.docx",
        placeholders: [
          { name: "summary", location: "body" },
          { name: "author", location: "header" }
        ]
      },
      { author: "{{författare}}" }
    );

    expect(next).toEqual({
      template_file_id: "new-file",
      template_name: "rapport.docx",
      placeholders: ["summary", "author"],
      bindings: {
        summary: "{{step_1.output.text}}",
        author: "{{författare}}"
      }
    });
  });

  it("resolves a legacy template_file_id-only config to the matching flow asset", () => {
    expect(
      resolveTemplateAssetSelection(
        {
          template_file_id: "file-1"
        },
        [
          { id: "asset-1", file_id: "file-1", name: "Mall 1" },
          { id: "asset-2", file_id: "file-2", name: "Mall 2" }
        ]
      )
    ).toEqual({
      asset: { id: "asset-1", file_id: "file-1", name: "Mall 1" },
      assetId: "asset-1"
    });
  });

  it("preserves orphaned bindings when a template is re-inspected", () => {
    const next = applyTemplateInspection(
      {
        template_file_id: "old-file",
        bindings: {
          summary: "{{step_1.output.text}}",
          removed_section: "{{step_2.output.text}}"
        }
      },
      {
        file_id: "new-file",
        file_name: "rapport.docx",
        placeholders: [{ name: "summary", location: "body" }]
      }
    );

    expect(next.bindings).toEqual({
      summary: "{{step_1.output.text}}",
      removed_section: "{{step_2.output.text}}"
    });
  });

  it("builds placeholder fallback rows from published config when no fresh inspection exists", () => {
    expect(
      listTemplatePlaceholders(null, {
        placeholders: ["summary", "author"]
      })
    ).toEqual([
      { name: "summary", location: "template", preview: null },
      { name: "author", location: "template", preview: null }
    ]);
  });

  it("updates one binding in-place", () => {
    expect(
      updateTemplateBinding(
        { bindings: { summary: "{{step_1.output.text}}" } },
        "author",
        "{{författare}}"
      )
    ).toEqual({
      bindings: {
        summary: "{{step_1.output.text}}",
        author: "{{författare}}"
      }
    });
  });

  it("builds advanced binding suggestions from form fields and prior steps", () => {
    const suggestions = buildTemplateBindingSuggestions({
      currentStepOrder: 4,
      labels,
      formSchema: {
        fields: [
          { name: "titel", type: "text" },
          { name: "författare", type: "text" }
        ]
      },
      steps: [
        { step_order: 1, user_description: "Inledning", output_type: "text" },
        { step_order: 2, user_description: "Analys", output_type: "json" },
        { step_order: 4, user_description: "Final", output_type: "docx" }
      ] as never
    });

    expect(suggestions).toEqual(
      expect.arrayContaining([
        { value: "{{titel}}", label: "Form field: titel", group: "form", outputType: "text" },
        {
          value: "{{författare}}",
          label: "Form field: författare",
          group: "form",
          outputType: "text"
        },
        {
          value: "{{step_1.output.text}}",
          label: "Inledning -> text",
          group: "step",
          outputType: "text"
        },
        {
          value: "{{step_2.output.structured}}",
          label: "Analys -> json",
          group: "step",
          outputType: "json"
        },
        { value: "{{datum}}", label: "Today", group: "system", outputType: "text" }
      ])
    );
    expect(suggestions.some((item) => item.value === "{{step_4.output.text}}")).toBe(false);
  });

  it("groups suggestions by source type", () => {
    const groups = groupTemplateBindingSuggestions(
      buildTemplateBindingSuggestions({
        currentStepOrder: 3,
        labels,
        formSchema: { fields: [{ name: "författare", type: "text" }] },
        steps: [{ step_order: 1, user_description: "Bakgrund", output_type: "text" }] as never
      }),
      labels
    );

    expect(groups.map((group) => group.key)).toEqual(["form", "step", "system"]);
  });

  it("builds auto-bindings from matching form fields and prior step names", () => {
    expect(
      buildTemplateBindingAutoSuggestions({
        placeholders: ["författare", "sammanfatta", "unknown_field"],
        currentStepOrder: 4,
        formSchema: {
          fields: [
            { name: "Författare", type: "text" },
            { name: "kurs", type: "text" }
          ]
        },
        steps: [
          { step_order: 1, user_description: "Transkribera", output_type: "text" },
          { step_order: 2, user_description: "Sammanfatta", output_type: "json" },
          { step_order: 4, user_description: "Final", output_type: "docx" }
        ] as never
      })
    ).toEqual({
      författare: "{{Författare}}",
      sammanfatta: "{{step_2.output.structured}}"
    });
  });

  it("applies obvious matches without overwriting manual bindings", () => {
    expect(
      applyAutoTemplateBindings({
        currentConfig: {
          bindings: {
            author: "{{författare}}"
          }
        },
        autoSuggestions: {
          author: "{{Författare}}",
          summary: "{{step_1.output.text}}"
        },
        placeholders: ["author", "summary"]
      })
    ).toEqual({
      bindings: {
        author: "{{författare}}",
        summary: "{{step_1.output.text}}"
      }
    });
  });

  it("computes readiness from configured placeholders and bindings", () => {
    expect(
      getTemplateFillReadiness({
        placeholders: ["summary", "author", "date"],
        bindings: {
          summary: "{{step_1.output.text}}",
          author: "{{författare}}"
        }
      })
    ).toEqual({
      total: 3,
      matched: 2,
      incomplete: true
    });
  });

  it("reports template-fill dry-run issues for missing template state and mappings", () => {
    expect(
      getTemplateFillDryRunIssues({
        step: {
          step_order: 4,
          output_mode: "template_fill",
          output_type: "docx",
          output_config: {
            placeholders: ["bakgrund", "analys"],
            bindings: {
              bakgrund: "{{step_1.output.text}}"
            }
          }
        } as never
      })
    ).toEqual(["Missing DOCX template.", "Missing mapping for template placeholder 'analys'."]);
  });

  it("reports forward references and orphaned mappings for template-fill dry runs", () => {
    expect(
      getTemplateFillDryRunIssues({
        step: {
          step_order: 3,
          output_mode: "template_fill",
          output_type: "docx",
          output_config: {
            template_file_id: "file-1",
            placeholders: ["bakgrund"],
            bindings: {
              bakgrund: "{{step_3.output.text}}",
              borttagen: "{{step_1.output.text}}"
            }
          }
        } as never
      })
    ).toEqual([
      "Template placeholder 'bakgrund' references step 3, which is not available before step 3.",
      "Template mapping 'borttagen' no longer exists in the selected DOCX template."
    ]);
  });

  it("reports wrong output type and missing placeholders in template-fill dry runs", () => {
    expect(
      getTemplateFillDryRunIssues({
        step: {
          step_order: 2,
          output_mode: "template_fill",
          output_type: "text",
          output_config: {
            template_file_id: "file-1",
            bindings: {}
          }
        } as never
      })
    ).toEqual([
      "Template fill requires Word output.",
      "No placeholders found in the selected DOCX template."
    ]);
  });

  it("accepts explicit empty bindings in template-fill dry runs", () => {
    expect(
      getTemplateFillDryRunIssues({
        step: {
          step_order: 2,
          output_mode: "template_fill",
          output_type: "docx",
          output_config: {
            template_file_id: "file-1",
            placeholders: ["valfri_del"],
            bindings: {
              valfri_del: ""
            }
          }
        } as never
      })
    ).toEqual([]);
  });

  it("builds rows with missing, matched, and orphaned states", () => {
    const suggestions = buildTemplateBindingSuggestions({
      currentStepOrder: 4,
      labels,
      formSchema: {
        fields: [{ name: "författare", type: "text" }]
      },
      steps: [
        { step_order: 1, user_description: "Bakgrund", output_type: "text" },
        { step_order: 2, user_description: "Kvalitetsgranskning", output_type: "json" }
      ] as never
    });

    const rows = listTemplateBindingRows({
      inspection: {
        file_id: "f1",
        file_name: "mall.docx",
        placeholders: [
          { name: "bakgrund", location: "body", preview: "Bakgrund..." },
          { name: "författare", location: "header", preview: null }
        ]
      },
      currentConfig: {
        placeholders: ["bakgrund", "författare"],
        bindings: {
          bakgrund: "{{step_1.output.text}}",
          removed: "{{step_2.output.structured}}",
          tom: ""
        }
      },
      suggestions,
      autoSuggestions: {
        bakgrund: "{{step_1.output.text}}"
      },
      labels
    });

    expect(rows).toEqual(
      expect.arrayContaining([
        expect.objectContaining({
          placeholderName: "bakgrund",
          status: "matched",
          autoSuggested: true,
          sourceLabel: "Bakgrund -> text"
        }),
        expect.objectContaining({
          placeholderName: "författare",
          status: "missing"
        }),
        expect.objectContaining({
          placeholderName: "removed",
          status: "orphaned",
          sourceOutputType: "json"
        })
      ])
    );
  });

  it("renders explicit empty bindings as a deliberate leave-empty choice", () => {
    const rows = listTemplateBindingRows({
      inspection: {
        file_id: "f1",
        file_name: "mall.docx",
        placeholders: [{ name: "optional_section", location: "body", preview: null }]
      },
      currentConfig: {
        placeholders: ["optional_section"],
        bindings: {
          optional_section: ""
        }
      },
      suggestions: [],
      labels
    });

    expect(rows).toEqual([
      expect.objectContaining({
        placeholderName: "optional_section",
        status: "matched",
        isExplicitEmpty: true,
        sourceLabel: "Leave empty"
      })
    ]);
  });
});
