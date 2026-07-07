import type { Schema } from "@/lib/api/models";

export type TemplateWizardNotice = "knowledge-recommended";
export type TemplateWizardBlockReason = "attachments-required" | "uploads-in-progress";

export type TemplateWizardAttachmentState = {
  fileId?: string;
  uploading: boolean;
};

export type TemplateWizardConfig = Schema<"AssistantTemplateWizard"> | Schema<"AppTemplateWizard">;

export type TemplateWizardSubmission =
  | {
      ok: true;
      additionalFields: Schema<"AdditionalField">[];
      notices: TemplateWizardNotice[];
    }
  | {
      ok: false;
      reason: TemplateWizardBlockReason;
    };

export function templateHasWizard(template: { wizard: TemplateWizardConfig }): boolean {
  return Boolean(template.wizard.attachments || template.wizard.collections);
}

export function validateTemplateWizardSubmission({
  wizard,
  collectionIds,
  attachments
}: {
  wizard: TemplateWizardConfig;
  collectionIds: string[];
  attachments: TemplateWizardAttachmentState[];
}): TemplateWizardSubmission {
  const additionalFields: Schema<"AdditionalField">[] = [];
  const notices: TemplateWizardNotice[] = [];

  if (wizard.collections?.required) {
    if (collectionIds.length > 0) {
      additionalFields.push({
        type: "groups",
        value: collectionIds.map((id) => ({ id }))
      });
    } else {
      notices.push("knowledge-recommended");
    }
  }

  if (wizard.attachments?.required) {
    if (attachments.some((attachment) => attachment.uploading)) {
      return { ok: false, reason: "uploads-in-progress" };
    }

    const fileIds = attachments.flatMap((attachment) =>
      attachment.fileId ? [attachment.fileId] : []
    );
    if (fileIds.length === 0) {
      return { ok: false, reason: "attachments-required" };
    }

    additionalFields.push({
      type: "attachments",
      value: fileIds.map((id) => ({ id }))
    });
  }

  return { ok: true, additionalFields, notices };
}

export function buildTemplateCreate(
  templateId: string,
  additionalFields: Schema<"AdditionalField">[]
): Schema<"TemplateCreate"> {
  return {
    id: templateId,
    additional_fields: additionalFields
  };
}
