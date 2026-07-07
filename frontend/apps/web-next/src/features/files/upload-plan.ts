export type FileUploadRules = {
  /** Mimetype list for the file picker's `accept` attribute (empty = any). */
  acceptString: string;
  /** Max number of files, or Infinity when unset. */
  maxFiles: number;
  /** Max combined size in bytes, or Infinity when unset. */
  maxSize: number;
  /** Per-mimetype size caps (bytes). */
  perTypeLimits: { mimetype: string; sizeLimit: number }[];
};

export type FileRestrictionsLike = {
  accepted_file_types: { mimetype: string; size_limit: number }[];
  limit: { max_files: number; max_size: number };
};

export type UploadPlanFile = {
  name: string;
  size: number;
  type?: string;
  mimetype?: string;
};

export type UploadRejectionReason =
  "unsupported-type" | "too-large" | "max-files" | "max-total-size";

export type UploadRejection<FileLike extends UploadPlanFile> = {
  file: FileLike;
  reason: UploadRejectionReason;
  limit?: number;
};

function fileUploadRules(
  restrictions: FileRestrictionsLike,
  options: { zeroMeansUnbounded: boolean }
): FileUploadRules {
  return {
    acceptString: restrictions.accepted_file_types.map((type) => type.mimetype).join(","),
    maxFiles:
      options.zeroMeansUnbounded && restrictions.limit.max_files === 0
        ? Infinity
        : restrictions.limit.max_files,
    maxSize:
      options.zeroMeansUnbounded && restrictions.limit.max_size === 0
        ? Infinity
        : restrictions.limit.max_size,
    perTypeLimits: restrictions.accepted_file_types.map((type) => ({
      mimetype: type.mimetype,
      sizeLimit: type.size_limit
    }))
  };
}

/**
 * Rules for configured app input fields. In that API, a zero limit means no
 * explicit cap, matching the legacy Svelte attachment manager.
 */
export function inputFieldRules(field: FileRestrictionsLike): FileUploadRules {
  return fileUploadRules(field, { zeroMeansUnbounded: true });
}

/**
 * Rules for resource-level attachment restrictions. A zero file cap disables
 * attachment uploads for that resource.
 */
export function fileRestrictionsRules(restrictions: FileRestrictionsLike): FileUploadRules {
  return fileUploadRules(restrictions, { zeroMeansUnbounded: false });
}

/** Plan a multi-file add against the field rules before any network upload starts. */
export function planFileUploads<FileLike extends UploadPlanFile>(
  incoming: FileLike[],
  currentFiles: { size: number }[],
  rules: FileUploadRules
): { accepted: FileLike[]; rejected: UploadRejection<FileLike>[] } {
  const acceptedTypes = new Set(rules.perTypeLimits.map((limit) => limit.mimetype));
  const accepted: FileLike[] = [];
  const rejected: UploadRejection<FileLike>[] = [];
  let plannedCount = currentFiles.length;
  let plannedSize = currentFiles.reduce((sum, file) => sum + file.size, 0);

  for (const file of incoming) {
    const mimetype = file.type ?? file.mimetype ?? "";
    if (acceptedTypes.size > 0 && !acceptedTypes.has(mimetype)) {
      rejected.push({ file, reason: "unsupported-type" });
      continue;
    }

    const perTypeLimit = rules.perTypeLimits.find((limit) => limit.mimetype === mimetype);
    if (
      perTypeLimit &&
      Number.isFinite(perTypeLimit.sizeLimit) &&
      file.size > perTypeLimit.sizeLimit
    ) {
      rejected.push({ file, reason: "too-large", limit: perTypeLimit.sizeLimit });
      continue;
    }

    if (plannedCount + 1 > rules.maxFiles) {
      rejected.push({ file, reason: "max-files", limit: rules.maxFiles });
      continue;
    }

    if (Number.isFinite(rules.maxSize) && plannedSize + file.size > rules.maxSize) {
      rejected.push({ file, reason: "max-total-size", limit: rules.maxSize });
      continue;
    }

    accepted.push(file);
    plannedCount += 1;
    plannedSize += file.size;
  }

  return { accepted, rejected };
}
