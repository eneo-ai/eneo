import { describe, expect, it } from "vitest";
import {
  buildTemplateCreate,
  templateHasWizard,
  validateTemplateWizardSubmission
} from "./template-create";
import type { Schema } from "@/lib/api/models";

const emptyWizard: Schema<"AssistantTemplateWizard"> = {
  attachments: null,
  collections: null
};

describe("template create helpers", () => {
  it("detects templates with at least one wizard section", () => {
    expect(templateHasWizard({ wizard: emptyWizard })).toBe(false);
    expect(
      templateHasWizard({
        wizard: { ...emptyWizard, collections: { required: true, title: null, description: null } }
      })
    ).toBe(true);
  });

  it("builds required collection and attachment additional fields", () => {
    const result = validateTemplateWizardSubmission({
      wizard: {
        collections: { required: true, title: null, description: null },
        attachments: { required: true, title: null, description: null }
      },
      collectionIds: ["group-1", "group-2"],
      attachments: [
        { fileId: "file-1", uploading: false },
        { fileId: "file-2", uploading: false }
      ]
    });

    expect(result).toEqual({
      ok: true,
      additionalFields: [
        { type: "groups", value: [{ id: "group-1" }, { id: "group-2" }] },
        { type: "attachments", value: [{ id: "file-1" }, { id: "file-2" }] }
      ],
      notices: []
    });
  });

  it("does not send optional wizard sections to the backend", () => {
    const result = validateTemplateWizardSubmission({
      wizard: {
        collections: { required: false, title: null, description: null },
        attachments: { required: false, title: null, description: null }
      },
      collectionIds: ["group-1"],
      attachments: [{ fileId: "file-1", uploading: false }]
    });

    expect(result).toEqual({ ok: true, additionalFields: [], notices: [] });
  });

  it("allows empty required collections as a non-blocking recommendation", () => {
    const result = validateTemplateWizardSubmission({
      wizard: {
        collections: { required: true, title: null, description: null },
        attachments: null
      },
      collectionIds: [],
      attachments: []
    });

    expect(result).toEqual({
      ok: true,
      additionalFields: [],
      notices: ["knowledge-recommended"]
    });
  });

  it("blocks required attachments while uploads are running or missing", () => {
    const wizard: Schema<"AssistantTemplateWizard"> = {
      collections: null,
      attachments: { required: true, title: null, description: null }
    };

    expect(
      validateTemplateWizardSubmission({
        wizard,
        collectionIds: [],
        attachments: [{ uploading: true }]
      })
    ).toEqual({ ok: false, reason: "uploads-in-progress" });

    expect(
      validateTemplateWizardSubmission({
        wizard,
        collectionIds: [],
        attachments: []
      })
    ).toEqual({ ok: false, reason: "attachments-required" });
  });

  it("builds a template create payload with an explicit additional_fields array", () => {
    expect(buildTemplateCreate("template-1", [])).toEqual({
      id: "template-1",
      additional_fields: []
    });
  });
});
