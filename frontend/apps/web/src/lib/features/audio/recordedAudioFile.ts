export type RecordingStopReason = "manual" | "limit" | "stall" | "error";

function inferRecordedAudioExtension(mimeType: string): string {
  const normalized = mimeType.split(";")[0]?.trim().toLowerCase() ?? "";
  switch (normalized) {
    case "audio/mp4":
    case "video/mp4":
      return "m4a";
    case "audio/webm":
    case "video/webm":
      return "webm";
    case "audio/mpeg":
      return "mp3";
    default: {
      const subtype = normalized.split("/")[1];
      return subtype && subtype.length > 0 ? subtype : "audio";
    }
  }
}

export function buildRecordedAudioFile(params: {
  blob: Blob;
  mimeType: string;
  fileNameBase: string;
}): File {
  const extension = inferRecordedAudioExtension(params.mimeType);
  return new File([params.blob], `${params.fileNameBase}.${extension}`, {
    type: params.mimeType
  });
}
