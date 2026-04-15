import type { Limits } from "@intric/intric-js";
import type { AttachmentRules } from "$lib/features/attachments/AttachmentManager";

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
  "application/msword",
  "application/vnd.ms-powerpoint",
  "application/json"
]);

export function getAIBuilderAttachmentRules(limits: Limits): AttachmentRules {
  const formats = limits.attachments.formats.filter((format) =>
    AI_BUILDER_SUPPORTED_MIMETYPES.has(format.mimetype)
  );

  return {
    maxTotalCount: Infinity,
    acceptedFormats: formats.map(({ mimetype, size }) => ({
      mimetype,
      maxSize: size
    })),
    acceptString: formats.map((format) => format.mimetype).join(",")
  };
}
