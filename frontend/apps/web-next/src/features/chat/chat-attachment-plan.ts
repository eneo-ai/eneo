export type ChatAttachmentUploadFile = {
  name: string;
  size: number;
  type?: string;
  mimetype?: string;
  lastModified?: number;
};

export type ChatAttachmentUploadFormat = {
  mimetype: string;
  size: number;
};

/** A file the server already holds, e.g. one sent earlier in the conversation. */
export type ChatAttachmentUploaded = {
  id: string;
  name: string;
  mimetype: string;
  size: number;
  /** The stored original's size; `size` counts a document's extracted text. */
  original_size?: number | null;
};

export type ChatAttachmentRejectionReason =
  "unsupported-type" | "too-large" | "max-files" | "duplicate";

export type ChatAttachmentRejection<FileLike extends ChatAttachmentUploadFile> = {
  file: FileLike;
  reason: ChatAttachmentRejectionReason;
  limit?: number;
};

function mimetypeOf(file: ChatAttachmentUploadFile): string {
  // Some files have a codec in the type, separated by a `;`.
  return (file.type ?? file.mimetype ?? "").split(";")[0] ?? "";
}

/** Whether two picked files are the same file: same name, size, type and modification time. */
export function isSameFile(a: ChatAttachmentUploadFile, b: ChatAttachmentUploadFile): boolean {
  return (
    a.name === b.name &&
    a.size === b.size &&
    mimetypeOf(a) === mimetypeOf(b) &&
    a.lastModified === b.lastModified
  );
}

/**
 * Whether a picked file is a file already uploaded: same name and type, and
 * the same number of bytes as the stored original. A document's `size` counts
 * its extracted text, so it only stands in where no original size is known.
 */
export function matchesUpload(
  file: ChatAttachmentUploadFile,
  uploaded: ChatAttachmentUploaded
): boolean {
  const bytes = uploaded.original_size ?? uploaded.size;
  return (
    uploaded.name === file.name && uploaded.mimetype === mimetypeOf(file) && bytes === file.size
  );
}

/**
 * Plans a pick against the partner's limits before any upload starts. A file
 * the composer already holds is skipped, and a file the server already has
 * (`findExisting`) is attached as it is instead of being uploaded again.
 */
export function planChatAttachmentUploads<FileLike extends ChatAttachmentUploadFile>(
  incoming: FileLike[],
  current: ChatAttachmentUploadFile[],
  formats: ChatAttachmentUploadFormat[],
  maxFiles: number,
  findExisting?: (file: FileLike) => ChatAttachmentUploaded | undefined
): {
  accepted: FileLike[];
  reused: { file: FileLike; uploaded: ChatAttachmentUploaded }[];
  rejected: ChatAttachmentRejection<FileLike>[];
} {
  const accepted: FileLike[] = [];
  const reused: { file: FileLike; uploaded: ChatAttachmentUploaded }[] = [];
  const rejected: ChatAttachmentRejection<FileLike>[] = [];
  const held: ChatAttachmentUploadFile[] = [...current];

  for (const file of incoming) {
    const mimetype = mimetypeOf(file);
    const format = formats.find((candidate) => candidate.mimetype === mimetype);
    if (!format) {
      rejected.push({ file, reason: "unsupported-type" });
      continue;
    }

    if (file.size > format.size) {
      rejected.push({ file, reason: "too-large", limit: format.size });
      continue;
    }

    // A file picked again (the same folder dropped twice, say) is already in
    // the list; it is not uploaded a second time and takes no slot.
    if (held.some((candidate) => isSameFile(candidate, file))) {
      rejected.push({ file, reason: "duplicate" });
      continue;
    }

    if (Number.isFinite(maxFiles) && held.length + 1 > maxFiles) {
      rejected.push({ file, reason: "max-files", limit: maxFiles });
      continue;
    }

    held.push(file);
    const existing = findExisting?.(file);
    if (existing) reused.push({ file, uploaded: existing });
    else accepted.push(file);
  }

  return { accepted, reused, rejected };
}
