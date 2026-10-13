export type ChatAttachmentUploadFile = {
  name: string;
  size: number;
  type?: string;
  mimetype?: string;
};

export type ChatAttachmentUploadFormat = {
  mimetype: string;
  size: number;
};

export type ChatAttachmentRejectionReason = "unsupported-type" | "too-large" | "max-files";

export type ChatAttachmentRejection<FileLike extends ChatAttachmentUploadFile> = {
  file: FileLike;
  reason: ChatAttachmentRejectionReason;
  limit?: number;
};

export function planChatAttachmentUploads<FileLike extends ChatAttachmentUploadFile>(
  incoming: FileLike[],
  currentCount: number,
  formats: ChatAttachmentUploadFormat[],
  maxFiles: number
): { accepted: FileLike[]; rejected: ChatAttachmentRejection<FileLike>[] } {
  const accepted: FileLike[] = [];
  const rejected: ChatAttachmentRejection<FileLike>[] = [];
  let plannedCount = currentCount;

  for (const file of incoming) {
    const mimetype = file.type ?? file.mimetype ?? "";
    const format = formats.find((candidate) => candidate.mimetype === mimetype);
    if (!format) {
      rejected.push({ file, reason: "unsupported-type" });
      continue;
    }

    if (file.size > format.size) {
      rejected.push({ file, reason: "too-large", limit: format.size });
      continue;
    }

    if (Number.isFinite(maxFiles) && plannedCount + 1 > maxFiles) {
      rejected.push({ file, reason: "max-files", limit: maxFiles });
      continue;
    }

    accepted.push(file);
    plannedCount += 1;
  }

  return { accepted, rejected };
}
