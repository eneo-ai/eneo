export function serializeEvidencePayload(payload: unknown): string {
  if (typeof payload === "string") {
    return payload;
  }
  return JSON.stringify(payload, null, 2) ?? "null";
}

type DownloadDeps = {
  createObjectURL: (blob: Blob) => string;
  revokeObjectURL: (url: string) => void;
  createAnchor: () => HTMLAnchorElement;
  appendAnchor: (anchor: HTMLAnchorElement) => void;
  removeAnchor: (anchor: HTMLAnchorElement) => void;
  scheduleRevoke: (callback: () => void) => void;
};

const defaultDownloadDeps: DownloadDeps = {
  createObjectURL: (blob) => URL.createObjectURL(blob),
  revokeObjectURL: (url) => URL.revokeObjectURL(url),
  createAnchor: () => document.createElement("a"),
  appendAnchor: (anchor) => document.body.appendChild(anchor),
  removeAnchor: (anchor) => anchor.remove(),
  scheduleRevoke: (callback) => setTimeout(callback, 0)
};

export function downloadJsonArtifact(
  fileName: string,
  payload: unknown,
  deps: Partial<DownloadDeps> = {},
): void {
  const resolved: DownloadDeps = { ...defaultDownloadDeps, ...deps };
  const blob = new Blob([JSON.stringify(payload, null, 2)], { type: "application/json" });
  const url = resolved.createObjectURL(blob);
  const anchor = resolved.createAnchor();
  anchor.href = url;
  anchor.download = fileName;
  resolved.appendAnchor(anchor);
  anchor.click();
  resolved.removeAnchor(anchor);
  resolved.scheduleRevoke(() => {
    resolved.revokeObjectURL(url);
  });
}
