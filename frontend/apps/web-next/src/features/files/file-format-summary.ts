export type AcceptedFormat = {
  mimetype: string;
  extensions: string[];
  maxSize: number;
};

export type FileFormatGroupKind = "documents" | "images" | "audio" | "other";

export type FileFormatGroup = {
  kind: FileFormatGroupKind;
  extensions: string[];
  maxSizeBytes: number | null;
};

const GROUP_ORDER: FileFormatGroupKind[] = ["documents", "images", "audio", "other"];

function groupKindFor(mimetype: string): FileFormatGroupKind {
  const type = mimetype.split("/")[0]?.trim().toLowerCase();
  if (type === "image") return "images";
  // Audio containers such as webm/mp4 have video MIME types but carry audio here.
  if (type === "audio" || type === "video") return "audio";
  if (type === "text" || type === "application") return "documents";
  return "other";
}

function normalizeExtension(extension: string): string {
  const trimmed = extension.trim().toLowerCase();
  return trimmed.startsWith(".") ? trimmed : `.${trimmed}`;
}

/** Group the server's accepted extensions and per-file limits for display. */
export function summarizeFileFormats(formats: readonly AcceptedFormat[]): FileFormatGroup[] {
  const extensionsByKind = new Map<FileFormatGroupKind, Set<string>>();
  const sizesByKind = new Map<FileFormatGroupKind, Set<number>>();

  for (const format of formats) {
    const kind = groupKindFor(format.mimetype);
    const extensions = extensionsByKind.get(kind) ?? new Set<string>();
    for (const extension of format.extensions) {
      if (extension.trim()) extensions.add(normalizeExtension(extension));
    }
    extensionsByKind.set(kind, extensions);

    const sizes = sizesByKind.get(kind) ?? new Set<number>();
    sizes.add(format.maxSize);
    sizesByKind.set(kind, sizes);
  }

  return GROUP_ORDER.flatMap((kind) => {
    const extensions = extensionsByKind.get(kind);
    if (!extensions || extensions.size === 0) return [];
    const sizes = [...(sizesByKind.get(kind) ?? [])];
    return [
      {
        kind,
        extensions: [...extensions].sort((a, b) => a.localeCompare(b)),
        maxSizeBytes: sizes.length === 1 ? (sizes[0] ?? null) : null
      }
    ];
  });
}
