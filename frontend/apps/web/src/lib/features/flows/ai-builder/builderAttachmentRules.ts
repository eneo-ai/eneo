import type { Limits } from "@eneo/eneo-js";
import type { AttachmentRules } from "$lib/features/attachments/AttachmentManager";
import { acceptedFormatsFromLimits } from "$lib/features/attachments/getAttachmentRules";

const AI_BUILDER_SUPPORTED_MIMETYPES = new Set([
  "text/markdown",
  "text/plain",
  "application/pdf",
  "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
  "text/csv",
  "application/csv",
  "application/vnd.openxmlformats-officedocument.presentationml.presentation",
  "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
  "application/vnd.ms-excel",
  "application/json"
]);

export function getAIBuilderAttachmentRules(limits: Limits): AttachmentRules {
  const formats = limits.attachments.formats.filter((format) =>
    AI_BUILDER_SUPPORTED_MIMETYPES.has(format.mimetype)
  );

  return {
    maxTotalCount: limits.attachments.ai_builder_max_count,
    acceptedFormats: acceptedFormatsFromLimits(formats),
    acceptString: formats.map((format) => format.mimetype).join(",")
  };
}
